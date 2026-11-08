"""Dark placeholder cards for chapters the user will replace with PowerPoint."""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parents[1] / "out" / "clips"


def card(path: Path, title: str, subtitle: str = "", footnote: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=(19.2, 10.8), dpi=100, facecolor="#0b1220")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor("#0b1220")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.text(0.08, 0.62, title, color="#f8fafc", fontsize=42, fontweight="bold", va="center")
    if subtitle:
        ax.text(0.08, 0.48, subtitle, color="#94a3b8", fontsize=24, va="center")
    if footnote:
        ax.text(0.08, 0.18, footnote, color="#64748b", fontsize=16, va="center")
    ax.text(0.08, 0.08, "Hack the Highway  |  slide placeholder - replace with your deck",
            color="#475569", fontsize=14)
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)


def render_slide_clip(stem: str, title: str, subtitle: str = "", footnote: str = "", seconds: float = 4.0) -> Path:
    png = OUT / f"_{stem}.png"
    mp4 = OUT / f"{stem}.mp4"
    card(png, title, subtitle, footnote)
    import subprocess
    subprocess.run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(png), "-t", str(seconds),
        "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        str(mp4),
    ], check=True, capture_output=True)
    return mp4
