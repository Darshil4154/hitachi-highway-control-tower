"""Knowledge graph over the company data (SPEC section 2).

Every traversal returns ``(result_ids, path_edges)`` where ``path_edges`` is a list of
``[src_node, EDGE, dst_node]`` triples so traces can cite exactly how a result was reached.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import networkx as nx

from . import config
from .data_loader import DataStore, get_store

Edge = list  # [src, EDGE, dst]

NODE_TYPES = [
    "Supplier", "Part", "Model", "Plant", "Shipment", "PartLot", "ProductionOrder", "CustomerOrder",
    "Customer", "Dealer", "Vehicle", "LoanerPool", "Alias", "Event", "Incident",
]

EDGE_SCHEMA: list[tuple[str, str, str]] = [
    ("SUPPLIES", "Supplier", "Part"),
    ("SENT_BY", "Shipment", "Supplier"),
    ("DELIVERS", "Shipment", "Part"),
    ("RECEIVED_AT", "Shipment", "Plant"),
    ("USED_IN", "Part", "Model"),
    ("CAN_BUILD", "Plant", "Model"),
    ("SCHEDULED_AT", "ProductionOrder", "Plant"),
    ("BUILDS", "ProductionOrder", "Model"),
    ("FULFILLS", "ProductionOrder", "CustomerOrder"),
    ("SOLD_THROUGH", "CustomerOrder", "Dealer"),
    ("ORDERED_BY", "CustomerOrder", "Customer"),
    ("LOT_OF", "PartLot", "Part"),
    ("LOT_FROM", "PartLot", "Supplier"),
    ("INSTALLED_AT", "PartLot", "Plant"),
    ("BUILT_FROM", "Vehicle", "ProductionOrder"),
    ("AT_DEALER", "Vehicle", "Dealer"),
    ("OWNED_BY", "Vehicle", "Customer"),
    ("HAS_POOL", "Dealer", "LoanerPool"),
    ("REFERS_TO", "Alias", "Supplier"),
    ("REFERS_TO", "Alias", "Part"),
    ("REFERS_TO", "Alias", "Plant"),
    ("MENTIONS", "Event", "Entity"),
    ("AFFECTS", "Incident", "ProductionOrder"),
    ("AFFECTS", "Incident", "Vehicle"),
]


def nid(kind: str, key: str) -> str:
    return f"{kind}:{key}"


def split_nid(node: str) -> tuple[str, str]:
    kind, _, key = node.partition(":")
    return kind, key


class KnowledgeGraph:
    def __init__(self, ds: DataStore):
        self.ds = ds
        self.g = nx.MultiDiGraph()
        self._build()

    # ------------------------------------------------------------ build
    def _node(self, kind: str, key: str, label: str, **attrs) -> str:
        n = nid(kind, key)
        clean = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in attrs.items() if v is not None}
        self.g.add_node(n, type=kind, label=label, **clean)
        return n

    def _edge(self, src: str, rel: str, dst: str) -> None:
        self.g.add_edge(src, dst, key=rel, rel=rel)

    def _build(self) -> None:
        ds = self.ds
        for m, seg in ds.models.items():
            self._node("Model", m, m.title(), model=m, segment=seg)
        for p in ds.parts.values():
            self._node("Part", p.part_id, p.name, part_id=p.part_id, name=p.name, category=p.category)
        for s in ds.suppliers.values():
            self._node("Supplier", s.supplier_id, s.name, supplier_id=s.supplier_id, name=s.name, city=s.city)
        for p in ds.plants.values():
            n = self._node("Plant", p.plant_id, p.name, plant_id=p.plant_id, name=p.name, city=p.city,
                           slots_per_day=p.slots_per_day)
            for m in sorted(ds.plant_models[p.plant_id]):
                self._edge(n, "CAN_BUILD", nid("Model", m))
        for model, parts in ds.bom.items():
            for part in sorted(parts):
                self._edge(nid("Part", part), "USED_IN", nid("Model", model))
        supplies: set[tuple[str, str]] = set()
        for sh in ds.shipments.values():
            n = self._node("Shipment", sh.shipment_id, sh.shipment_id, shipment_id=sh.shipment_id,
                           supplier_id=sh.supplier_id, part_id=sh.part_id, plant_id=sh.plant_id,
                           eta_date=sh.eta_date, covers_days=sh.covers_days)
            self._edge(n, "SENT_BY", nid("Supplier", sh.supplier_id))
            self._edge(n, "DELIVERS", nid("Part", sh.part_id))
            self._edge(n, "RECEIVED_AT", nid("Plant", sh.plant_id))
            supplies.add((sh.supplier_id, sh.part_id))
        for lot in ds.part_lots.values():
            n = self._node("PartLot", lot.lot_id, lot.lot_id, lot_id=lot.lot_id, part_id=lot.part_id,
                           supplier_id=lot.supplier_id, plant_id=lot.plant_id,
                           first_build_date=lot.first_build_date, last_build_date=lot.last_build_date)
            self._edge(n, "LOT_OF", nid("Part", lot.part_id))
            self._edge(n, "LOT_FROM", nid("Supplier", lot.supplier_id))
            self._edge(n, "INSTALLED_AT", nid("Plant", lot.plant_id))
            supplies.add((lot.supplier_id, lot.part_id))
        for sup, part in sorted(supplies):
            self._edge(nid("Supplier", sup), "SUPPLIES", nid("Part", part))
        for c in ds.customers.values():
            self._node("Customer", c.customer_id, c.name, customer_id=c.customer_id, name=c.name, tier=c.tier)
        for d in ds.dealers.values():
            n = self._node("Dealer", d.dealer_id, d.name, dealer_id=d.dealer_id, name=d.name, city=d.city,
                           region=d.region, transit_days=d.transit_days)
            pool = self._node("LoanerPool", d.dealer_id, f"Loaners {d.dealer_id}", dealer_id=d.dealer_id,
                              loaners_available=ds.loaners.get(d.dealer_id, 0))
            self._edge(n, "HAS_POOL", pool)
        for po in ds.production_orders.values():
            n = self._node("ProductionOrder", po.production_order_id, po.production_order_id,
                           production_order_id=po.production_order_id, plant_id=po.plant_id,
                           build_date=po.build_date, model=po.model, units=po.units)
            self._edge(n, "SCHEDULED_AT", nid("Plant", po.plant_id))
            self._edge(n, "BUILDS", nid("Model", po.model))
        for co in ds.customer_orders.values():
            n = self._node("CustomerOrder", co.customer_order_id, co.customer_order_id,
                           customer_order_id=co.customer_order_id, production_order_id=co.production_order_id,
                           dealer_id=co.dealer_id, customer_id=co.customer_id, model=co.model,
                           promised_date=co.promised_date)
            self._edge(nid("ProductionOrder", co.production_order_id), "FULFILLS", n)
            self._edge(n, "SOLD_THROUGH", nid("Dealer", co.dealer_id))
            self._edge(n, "ORDERED_BY", nid("Customer", co.customer_id))
        for v in ds.vehicles.values():
            n = self._node("Vehicle", v.vin, v.vin, vin=v.vin, production_order_id=v.production_order_id,
                           model=v.model, plant_id=v.plant_id, build_date=v.build_date, dealer_id=v.dealer_id,
                           status=v.status, customer_id=v.customer_id)
            self._edge(n, "BUILT_FROM", nid("ProductionOrder", v.production_order_id))
            self._edge(n, "AT_DEALER", nid("Dealer", v.dealer_id))
            if v.status == "sold" and v.customer_id:
                self._edge(n, "OWNED_BY", nid("Customer", v.customer_id))
        for a in ds.aliases:
            kind = {"plant": "Plant", "part": "Part", "supplier": "Supplier"}[a.entity_type]
            n = self._node("Alias", a.alias, a.alias, alias=a.alias, entity_type=a.entity_type, entity_id=a.entity_id)
            self._edge(n, "REFERS_TO", nid(kind, a.entity_id))

    # ------------------------------------------------------------ helpers
    def out_nodes(self, node: str, rel: str) -> list[str]:
        return sorted({v for _, v, k in self.g.out_edges(node, keys=True) if k == rel})

    def in_nodes(self, node: str, rel: str) -> list[str]:
        return sorted({u for u, _, k in self.g.in_edges(node, keys=True) if k == rel})

    def attr(self, node: str, name: str):
        return self.g.nodes[node].get(name)

    def _po_date(self, po_node: str) -> date:
        return date.fromisoformat(self.attr(po_node, "build_date"))

    def _sorted_pos(self, po_nodes: Iterable[str]) -> list[str]:
        return sorted(po_nodes, key=lambda n: (self.attr(n, "build_date"), n))

    # ------------------------------------------------------------ traversals
    def models_using_part(self, part_id: str) -> tuple[list[str], list[Edge]]:
        part = nid("Part", part_id)
        models = self.out_nodes(part, "USED_IN")
        return [split_nid(m)[1] for m in models], [[part, "USED_IN", m] for m in models]

    def orders_needing_part(
        self, part_id: str, plant_id: str, date_from: date, date_until_excl: date
    ) -> tuple[list[str], list[Edge]]:
        """R1: orders at the receiving plant whose model BOM has the part, build date in [from, until_excl)."""
        part, plant = nid("Part", part_id), nid("Plant", plant_id)
        result, edges = [], []
        for model in self.out_nodes(part, "USED_IN"):
            for po in self.in_nodes(model, "BUILDS"):
                if plant not in self.out_nodes(po, "SCHEDULED_AT"):
                    continue
                if date_from <= self._po_date(po) < date_until_excl:
                    result.append(po)
                    edges += [[part, "USED_IN", model], [po, "BUILDS", model], [po, "SCHEDULED_AT", plant]]
        ordered = self._sorted_pos(result)
        return [split_nid(p)[1] for p in ordered], _dedupe(edges)

    def orders_at_plant(self, plant_id: str, date_from: date, date_to_incl: date) -> tuple[list[str], list[Edge]]:
        """R2: every order at the plant with build date in [from, to] (inclusive both ends)."""
        plant = nid("Plant", plant_id)
        result = [po for po in self.in_nodes(plant, "SCHEDULED_AT") if date_from <= self._po_date(po) <= date_to_incl]
        ordered = self._sorted_pos(result)
        return [split_nid(p)[1] for p in ordered], [[po, "SCHEDULED_AT", plant] for po in ordered]

    def customer_orders_of(self, po_ids: Iterable[str]) -> tuple[list[str], list[Edge]]:
        cos, edges = [], []
        for po_id in po_ids:
            po = nid("ProductionOrder", po_id)
            for co in self.out_nodes(po, "FULFILLS"):
                cos.append(co)
                edges.append([po, "FULFILLS", co])
                for d in self.out_nodes(co, "SOLD_THROUGH"):
                    edges.append([co, "SOLD_THROUGH", d])
                for c in self.out_nodes(co, "ORDERED_BY"):
                    edges.append([co, "ORDERED_BY", c])
        return sorted(split_nid(c)[1] for c in set(cos)), _dedupe(edges)

    def vehicles_for_lot(self, lot_id: str) -> tuple[list[str], list[Edge]]:
        """R6: vehicles at the lot plant, built inside the lot dates, from orders of models that use the part."""
        lot = nid("PartLot", lot_id)
        part = self.out_nodes(lot, "LOT_OF")[0]
        plant = self.out_nodes(lot, "INSTALLED_AT")[0]
        first = date.fromisoformat(self.attr(lot, "first_build_date"))
        last = date.fromisoformat(self.attr(lot, "last_build_date"))
        edges: list[Edge] = [[lot, "LOT_OF", part], [lot, "INSTALLED_AT", plant]]
        vins = []
        for model in self.out_nodes(part, "USED_IN"):
            for po in self.in_nodes(model, "BUILDS"):
                if plant not in self.out_nodes(po, "SCHEDULED_AT") or not first <= self._po_date(po) <= last:
                    continue
                for v in self.in_nodes(po, "BUILT_FROM"):
                    vins.append(v)
                    edges += [[part, "USED_IN", model], [po, "BUILDS", model], [po, "SCHEDULED_AT", plant],
                              [v, "BUILT_FROM", po]]
                    edges += [[v, "AT_DEALER", d] for d in self.out_nodes(v, "AT_DEALER")]
                    edges += [[v, "OWNED_BY", c] for c in self.out_nodes(v, "OWNED_BY")]
        return sorted(split_nid(v)[1] for v in set(vins)), _dedupe(edges)

    def find_shipment(
        self, part_id: str, plant_id: str, supplier_id: str | None = None, eta_date: date | None = None
    ) -> tuple[list[str], list[Edge]]:
        part, plant = nid("Part", part_id), nid("Plant", plant_id)
        result, edges = [], []
        for sh in self.in_nodes(part, "DELIVERS"):
            if plant not in self.out_nodes(sh, "RECEIVED_AT"):
                continue
            sup = self.out_nodes(sh, "SENT_BY")[0]
            if supplier_id and sup != nid("Supplier", supplier_id):
                continue
            if eta_date and self.attr(sh, "eta_date") != eta_date.isoformat():
                continue
            result.append(sh)
            edges += [[sh, "SENT_BY", sup], [sh, "DELIVERS", part], [sh, "RECEIVED_AT", plant]]
        return sorted(split_nid(s)[1] for s in result), _dedupe(edges)

    def find_lots(
        self, part_id: str, plant_id: str, supplier_id: str | None = None,
        window_from: date | None = None, window_to: date | None = None, mode: str = "equal",
    ) -> tuple[list[str], list[Edge]]:
        """mode='equal': lot dates equal the window; mode='inside': lot fully inside the window."""
        part, plant = nid("Part", part_id), nid("Plant", plant_id)
        result, edges = [], []
        for lot in self.in_nodes(part, "LOT_OF"):
            if plant not in self.out_nodes(lot, "INSTALLED_AT"):
                continue
            sup = self.out_nodes(lot, "LOT_FROM")[0]
            if supplier_id and sup != nid("Supplier", supplier_id):
                continue
            first = date.fromisoformat(self.attr(lot, "first_build_date"))
            last = date.fromisoformat(self.attr(lot, "last_build_date"))
            if window_from and window_to:
                if mode == "equal" and not (first == window_from and last == window_to):
                    continue
                if mode == "inside" and not (window_from <= first and last <= window_to):
                    continue
            result.append(lot)
            edges += [[lot, "LOT_OF", part], [lot, "LOT_FROM", sup], [lot, "INSTALLED_AT", plant]]
        return sorted(split_nid(x)[1] for x in result), _dedupe(edges)

    def path_between(self, a: str, b: str) -> list[Edge]:
        und = self.g.to_undirected(as_view=True)
        try:
            nodes = nx.shortest_path(und, a, b)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []
        out = []
        for u, v in zip(nodes, nodes[1:]):
            if self.g.has_edge(u, v):
                out.append([u, next(iter(self.g[u][v])), v])
            else:
                out.append([v, next(iter(self.g[v][u])), u])
        return out

    def explain_path(self, edges: list[Edge], limit: int = 8, ordered: bool = False) -> str:
        """Readable chain, e.g. 'SH-0182 -[DELIVERS]-> CAM-360 -[USED_IN]-> VOYAGER <-[BUILDS]- PO-0412'.
        ordered=True keeps the given edge order (a pre-built connected chain)."""
        if not edges:
            return ""
        chain = list(edges) if ordered else _chain(edges)
        cur = chain[0][0]
        if len(chain) > 1 and chain[0][0] in (chain[1][0], chain[1][2]) and chain[0][2] not in (chain[1][0], chain[1][2]):
            cur = chain[0][2]
        parts = [split_nid(cur)[1]]
        for src, rel, dst in chain[:limit]:
            if src == cur:
                parts.append(f"-[{rel}]-> {split_nid(dst)[1]}")
                cur = dst
            elif dst == cur:
                parts.append(f"<-[{rel}]- {split_nid(src)[1]}")
                cur = src
            else:
                parts.append(f"| {split_nid(src)[1]} -[{rel}]-> {split_nid(dst)[1]}")
                cur = dst
        text = " ".join(parts)
        if len(edges) > len(chain[:limit]):
            text += f"  (+{len(edges) - len(chain[:limit])} more edges)"
        return text

    # ------------------------------------------------------------ exports
    def stats(self) -> dict:
        nodes = Counter(d["type"] for _, d in self.g.nodes(data=True))
        edges = Counter(k for _, _, k in self.g.edges(keys=True))
        return {"nodes_total": self.g.number_of_nodes(), "edges_total": self.g.number_of_edges(),
                "nodes_by_type": dict(sorted(nodes.items())), "edges_by_type": dict(sorted(edges.items()))}

    def export(self, out_dir: Path | None = None) -> list[Path]:
        out = Path(out_dir or config.EXPORTS_DIR)
        out.mkdir(parents=True, exist_ok=True)
        paths = [out / "knowledge_graph.graphml", out / "ontology.ttl", out / "graph_stats.json",
                 out / "ontology_schema.png"]
        nx.write_graphml(self.g, paths[0])
        self._export_ttl(paths[1])
        paths[2].write_text(json.dumps(self.stats(), indent=2), encoding="utf-8")
        self._export_schema_png(paths[3])
        return paths

    def _export_ttl(self, path: Path) -> None:
        from rdflib import RDF, RDFS, Graph, Literal, Namespace, OWL, URIRef
        from urllib.parse import quote

        ns = Namespace("https://wackywheels.example/ontology#")
        rdf = Graph()
        rdf.bind("ww", ns)
        rdf.bind("owl", OWL)
        for t in NODE_TYPES:
            rdf.add((ns[t], RDF.type, OWL.Class))
            rdf.add((ns[t], RDFS.label, Literal(t)))
        for rel, src, dst in EDGE_SCHEMA:
            p = ns[rel]
            rdf.add((p, RDF.type, OWL.ObjectProperty))
            rdf.add((p, RDFS.label, Literal(rel)))
            if src in NODE_TYPES:
                rdf.add((p, RDFS.domain, ns[src]))
            if dst in NODE_TYPES and rel not in ("REFERS_TO", "AFFECTS"):
                rdf.add((p, RDFS.range, ns[dst]))
        uri = lambda n: URIRef(ns + quote(n.replace(":", "/"), safe="/-_"))
        for n, d in self.g.nodes(data=True):
            u = uri(n)
            rdf.add((u, RDF.type, ns[d["type"]]))
            rdf.add((u, RDFS.label, Literal(d["label"])))
            for k, v in d.items():
                if k not in ("type", "label"):
                    rdf.add((u, ns[k], Literal(v)))
        for a, b, k in self.g.edges(keys=True):
            rdf.add((uri(a), ns[k], uri(b)))
        rdf.serialize(destination=str(path), format="turtle")

    def _export_schema_png(self, path: Path) -> None:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        types = [t for t in NODE_TYPES if t not in ("Event", "Incident", "Alias")]
        pos = {
            "Supplier": (0, 3), "Shipment": (1.6, 4.2), "PartLot": (1.6, 1.8), "Part": (3, 3), "Model": (5, 3),
            "Plant": (4, 5), "ProductionOrder": (6.5, 4.5), "Vehicle": (6.5, 1.2), "CustomerOrder": (8.5, 4.5),
            "Customer": (10.5, 3), "Dealer": (8.8, 1.8), "LoanerPool": (10.5, 0.6),
        }
        sg = nx.MultiDiGraph()
        sg.add_nodes_from(types)
        for rel, s, d in EDGE_SCHEMA:
            if s in types and d in types:
                sg.add_edge(s, d, key=rel)
        colors = {"Supplier": "#f59e0b", "Shipment": "#fbbf24", "PartLot": "#a855f7", "Part": "#fb923c",
                  "Model": "#22c55e", "Plant": "#ef4444", "ProductionOrder": "#3b82f6", "CustomerOrder": "#06b6d4",
                  "Customer": "#14b8a6", "Dealer": "#6366f1", "Vehicle": "#8b5cf6", "LoanerPool": "#64748b"}
        fig, ax = plt.subplots(figsize=(15, 7.5))
        ax.set_title("Wacky Wheels ontology - node types and relationships", fontsize=15, weight="bold")
        nx.draw_networkx_nodes(sg, pos, node_color=[colors[n] for n in sg.nodes], node_size=3600, ax=ax, alpha=0.95)
        names = {n: n.replace("Order", "\nOrder").replace("Pool", "\nPool") for n in sg.nodes}
        nx.draw_networkx_labels(sg, pos, labels=names, font_size=8.5, font_color="white", font_weight="bold", ax=ax)
        nx.draw_networkx_edges(sg, pos, ax=ax, arrows=True, arrowsize=16, node_size=3600, edge_color="#475569",
                               connectionstyle="arc3,rad=0.08")
        labels = {(u, v): k for u, v, k in sg.edges(keys=True)}
        nx.draw_networkx_edge_labels(sg, pos, edge_labels=labels, font_size=7.5, ax=ax,
                                     bbox={"boxstyle": "round", "fc": "white", "ec": "#cbd5e1"})
        ax.text(0, -0.4, "Runtime: Event -[MENTIONS]-> entity, Incident -[AFFECTS]-> ProductionOrder / Vehicle;  "
                         "Alias -[REFERS_TO]-> Supplier / Part / Plant", fontsize=9, color="#334155")
        ax.axis("off")
        fig.tight_layout()
        fig.savefig(path, dpi=140)
        plt.close(fig)


def _dedupe(edges: list[Edge]) -> list[Edge]:
    seen, out = set(), []
    for e in edges:
        t = tuple(e)
        if t not in seen:
            seen.add(t)
            out.append(list(e))
    return out


def _chain(edges: list[Edge]) -> list[Edge]:
    """Greedy walk through connected edges starting from the first, for a one-line explanation."""
    chain, used = [edges[0]], {0}
    cur = edges[0][2]
    while True:
        nxt = None
        for i, (s, _, d) in enumerate(edges):
            if i not in used and (s == cur or d == cur):
                nxt = i
                break
        if nxt is None:
            return chain
        used.add(nxt)
        s, _, d = edges[nxt]
        chain.append(edges[nxt])
        cur = d if s == cur else s


@lru_cache(maxsize=1)
def get_graph() -> KnowledgeGraph:
    return KnowledgeGraph(get_store())


def main() -> None:
    ap = argparse.ArgumentParser(description="Build and export the Wacky Wheels knowledge graph")
    ap.add_argument("--export", action="store_true")
    args = ap.parse_args()
    kg = get_graph()
    print(json.dumps(kg.stats(), indent=2))
    if args.export:
        for p in kg.export():
            print("wrote", p.relative_to(config.ROOT))


if __name__ == "__main__":
    main()
