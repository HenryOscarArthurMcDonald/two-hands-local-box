"""Create a realistic Physics + cross-domain sample mini-corpus for testing the pilot harness."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_utils import WORKSPACE_ROOT

SAMPLE_DIR = WORKSPACE_ROOT / "raw_corpus" / "sample_pilot"


def seed_sample_corpus(target_dir: Path = SAMPLE_DIR) -> list[Path]:
    """Write sample Physics and non-Physics notes for validating the single-chapter pilot."""
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    physics_chat = [
        {
            "author": "user",
            "created_at": "2026-10-14T09:10:00Z",
            "content": (
                "Physics note: People say light slows down in water because photons bounce around "
                "between water molecules like pinballs and travel a longer zigzag path. "
                "Is that actually true, or does phase velocity change for another reason?"
            ),
        },
        {
            "author": "assistant",
            "created_at": "2026-10-14T09:11:00Z",
            "content": (
                "In water (refractive index n approx 1.333), the macroscopic phase velocity is v = c / n "
                "approx 0.75 c. However, photons do not bounce like pinballs (random scattering would blur "
                "all images!). Instead, the electromagnetic wave drives oscillating dipoles in water, and "
                "the phase superposition of the incident and re-radiated waves reduces the effective phase velocity "
                "while underlying electromagnetic interactions still propagate at c."
            ),
        },
        {
            "author": "user",
            "created_at": "2026-10-18T14:22:00Z",
            "content": (
                "Conjecture on causality and energy conservation: If two wave packets interfere destructively "
                "in one region, does energy vanish, or must energy shift elsewhere by conservation laws? "
                "Also, in a closed system, Noether symmetry under time translation locks total energy."
            ),
        },
    ]
    p1 = target_dir / "physics_notes.json"
    p1.write_text(json.dumps(physics_chat, indent=2), encoding="utf-8")
    written.append(p1)

    cross_domain_md = target_dir / "systems_and_woodworking_notes.md"
    cross_domain_md.write_text(
        "# Non-Physics Notes: Systems, Thermostats, and Mousetraps\n\n"
        "A mechanical mousetrap is a stateless forward pass: tension is pre-loaded, trigger input fires "
        "a deterministic cascade, and it holds zero memory afterward.\n\n"
        "By contrast, a thermostat wraps a stateless comparator inside a feedback loop, just as wave "
        "refraction emerges from continuous phase superposition between field and medium.\n\n"
        "In woodworking, steam-bending oak relies on a phase transition in lignin plasticity rather "
        "than brute force: same structural invariance, different substrate.\n",
        encoding="utf-8",
    )
    written.append(cross_domain_md)

    return written


if __name__ == "__main__":
    files = seed_sample_corpus()
    print("Seeded sample pilot files:", [str(f) for f in files])
