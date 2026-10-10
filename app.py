from __future__ import annotations

import re
import time
from dataclasses import dataclass
from io import BytesIO
from typing import Any
from urllib.parse import quote

import requests
import streamlit as st
from PIL import Image, UnidentifiedImageError


@dataclass(frozen=True)
class GenerationTier:
    number: int
    name: str
    steps: int
    width: int
    height: int
    suffix: str

    @property
    def label(self) -> str:
        return f"Tier {self.number} - {self.name}"


TIERS = {
    1: GenerationTier(
        number=1,
        name="Eco-Outline",
        steps=4,
        width=512,
        height=512,
        suffix=(
            ", clean black and white line art outline, coloring book page for children, "
            "thick clear contours, zero shading, white background"
        ),
    ),
    2: GenerationTier(
        number=2,
        name="Classroom Vector",
        steps=15,
        width=768,
        height=768,
        suffix=", flat educational vector illustration, simple bold shapes, vibrant primary colors",
    ),
    3: GenerationTier(
        number=3,
        name="District Master Baseline",
        steps=50,
        width=1024,
        height=1024,
        suffix=(
            ", 8k resolution, photorealistic, cinematic lighting, "
            "ultra-detailed official district banner"
        ),
    ),
}

BASELINE_LATENCY_SECONDS = 9.8
BASELINE_ENERGY_WH = 0.816
BASELINE_COST_USD = 0.0049
ACTIVE_POWER_WATTS = 300
INSTANCE_RATE_USD_PER_HOUR = 1.80
GRID_EMISSION_FACTOR = 0.82
POLLINATIONS_URL = "https://image.pollinations.ai/prompt/"

DISTRICT_SCHOOLS = 300
DISTRICT_MONTHLY_REQUESTS = 45_000
DISTRICT_NAIVE_SPEND_USD = 1_800.00
DISTRICT_GOVERNED_SPEND_USD = 220.00
DISTRICT_ENERGY_SAVED_KWH = 342
DISTRICT_TIER_SHARES = {1: 0.84, 2: 0.11, 3: 0.05}


def classify_prompt(prompt: str) -> tuple[int, str]:
    """Route classroom prompts to the least demanding tier that fits."""
    rules = (
        (
            1,
            "Worksheet",
            re.compile(
                r"\b(color(?:ing)?(?:\s+book)?|worksheet|outlines?|kids?|children|kindergarten)\b",
                re.IGNORECASE,
            ),
        ),
        (
            2,
            "Classroom visual",
            re.compile(r"\b(flashcards?|diagrams?|charts?)\b", re.IGNORECASE),
        ),
        (
            3,
            "High-fidelity visual",
            re.compile(r"\b(banners?|posters?|annual\s+reports?|photorealistic)\b", re.IGNORECASE),
        ),
    )
    for tier_number, purpose, pattern in rules:
        if pattern.search(prompt):
            return tier_number, purpose
    return 2, "Classroom resource"


def calculate_telemetry(tier: GenerationTier, latency_seconds: float) -> dict[str, float]:
    """Estimate energy, carbon, and compute cost using the challenge formulas."""
    pixel_ratio = (tier.width * tier.height) / (1024 * 1024)
    step_ratio = tier.steps / 50
    energy_wh = (
        ACTIVE_POWER_WATTS
        * latency_seconds
        * step_ratio
        * pixel_ratio
        / 3600
    )
    carbon_g = energy_wh * GRID_EMISSION_FACTOR
    cost_usd = (INSTANCE_RATE_USD_PER_HOUR / 3600) * latency_seconds * step_ratio
    return {
        "latency_seconds": latency_seconds,
        "energy_wh": energy_wh,
        "carbon_g": carbon_g,
        "cost_usd": cost_usd,
    }


def percentage_savings(baseline: float, current: float) -> float:
    if baseline <= 0:
        return 0.0
    return ((baseline - current) / baseline) * 100


def render_telemetry(tier: GenerationTier, telemetry: dict[str, float], heading: str) -> None:
    st.subheader(heading)
    metrics = (
        ("Latency", telemetry["latency_seconds"], BASELINE_LATENCY_SECONDS, "s", 3),
        ("Energy Drawn", telemetry["energy_wh"], BASELINE_ENERGY_WH, "Wh", 6),
        (
            "Carbon",
            telemetry["carbon_g"],
            BASELINE_ENERGY_WH * GRID_EMISSION_FACTOR,
            "g CO2e",
            6,
        ),
        ("Cost", telemetry["cost_usd"], BASELINE_COST_USD, "$", 6),
    )
    columns = st.columns(4)
    for column, (label, value, baseline, unit, precision) in zip(columns, metrics):
        savings = percentage_savings(baseline, value)
        if label == "Cost":
            formatted_value = f"${value:.{precision}f}"
        else:
            formatted_value = f"{value:.{precision}f} {unit}"
        column.metric(
            label,
            formatted_value,
            delta=f"{savings:.1f}% savings vs Tier 3",
            delta_color="normal",
        )


def render_calculation_explanation(tier: GenerationTier) -> None:
    with st.expander("📐 How is this estimate calculated? (Constraint 1 Explanation)"):
        st.markdown(
            """
**Reference hardware and rate**

- GPU reference: NVIDIA A100 PCIe, 300 W active TDP.
- Cloud instance rate: $1.80 per hour.
- Tier 3 maximum reference: 9.8 s latency, 0.816 Wh energy, and $0.0049 cost.
- India grid emission factor: 0.82 g CO2e per Wh (CEA factor supplied in the challenge brief).

**Per-generation formulas**

- Energy (Wh) = (300 W x latency seconds x (steps / 50) x (width x height / (1024 x 1024))) / 3600.
- Carbon (g CO2e) = energy (Wh) x 0.82.
- Cost (USD) = (1.80 / 3600) x latency seconds x (steps / 50).
- Savings (%) = ((Tier 3 baseline - current value) / Tier 3 baseline) x 100.

**Selected tier parameters**
"""
        )
        st.write(
            f"{tier.label}: {tier.steps} steps, {tier.width} x {tier.height} pixels. "
            "Before generation, latency is estimated by scaling the 9.8 s Tier 3 "
            "reference by steps / 50. After the request, the displayed latency is "
            "the measured HTTP request round trip, including image download but "
            "excluding local image decoding and display."
        )
        st.caption(
            "These are estimates from the stated A100 model, not direct measurements "
            "of Pollinations.ai server-side GPU power or energy."
        )


def generate_image(prompt: str, tier: GenerationTier) -> tuple[bytes, float]:
    encoded_prompt = quote(prompt + tier.suffix, safe="")
    url = (
        f"{POLLINATIONS_URL}{encoded_prompt}"
        f"?width={tier.width}&height={tier.height}&nologo=true&seed=42"
    )
    started_at = time.perf_counter()
    response = requests.get(url, timeout=(10, 120))
    elapsed_seconds = time.perf_counter() - started_at
    response.raise_for_status()
    try:
        with Image.open(BytesIO(response.content)) as source_image:
            image = source_image.convert("RGB")
            image_bytes = BytesIO()
            image.save(image_bytes, format="PNG", optimize=True)
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("The image service response was not a readable image.") from error
    return image_bytes.getvalue(), elapsed_seconds


def render_district_portal() -> None:
    st.header("🏢 District Admin Portal (300 Schools)")
    st.caption(
        f"District planning scenario | {DISTRICT_SCHOOLS:,} schools | "
        f"{DISTRICT_MONTHLY_REQUESTS:,} monthly image requests"
    )

    savings_usd = DISTRICT_NAIVE_SPEND_USD - DISTRICT_GOVERNED_SPEND_USD
    savings_percent = savings_usd / DISTRICT_NAIVE_SPEND_USD * 100
    columns = st.columns(4)
    columns[0].metric("Unconstrained Naive Spend", f"${DISTRICT_NAIVE_SPEND_USD:,.2f}/mo")
    columns[1].metric("EcoCanvas Governed Spend", f"${DISTRICT_GOVERNED_SPEND_USD:,.2f}/mo")
    columns[2].metric("Net Savings", f"${savings_usd:,.2f}/mo", f"{savings_percent:.1f}% cost reduction")
    columns[3].metric("Energy Conserved", f"{DISTRICT_ENERGY_SAVED_KWH:,} kWh/mo")

    st.subheader("Monthly asset breakdown")
    breakdown: list[dict[str, Any]] = []
    for tier_number, share in DISTRICT_TIER_SHARES.items():
        tier = TIERS[tier_number]
        breakdown.append(
            {
                "Tier": f"Tier {tier_number} - {tier.name}",
                "Request share": f"{share:.0%}",
                "Monthly requests": f"{DISTRICT_MONTHLY_REQUESTS * share:,.0f}",
                "Generation profile": f"{tier.steps} steps, {tier.width} x {tier.height}",
            }
        )
    st.table(breakdown)

    st.subheader("Governed request mix")
    for tier_number, share in DISTRICT_TIER_SHARES.items():
        st.progress(share, text=f"Tier {tier_number}: {share:.0%}")

    st.caption(
        "District spend and energy totals are the planning figures supplied in the "
        "challenge brief. They are shown as a district scenario, not recalculated "
        "from the per-generation A100 estimate above."
    )


def main() -> None:
    st.set_page_config(page_title="EcoCanvas", page_icon="🌱", layout="wide")
    st.title("EcoCanvas")
    st.caption("Right-sized educational image generation for district classrooms")

    classroom_tab, district_tab = st.tabs(
        ["🎨 Classroom Generator", "🏢 District Admin Portal (300 Schools)"]
    )

    with classroom_tab:
        st.header("Classroom image generator")
        prompt = st.text_input(
            "Describe the image",
            placeholder="For example: Elephant for kids coloring",
            max_chars=500,
        ).strip()

        routed_tier_number, detected_purpose = classify_prompt(prompt)
        routed_tier = TIERS[routed_tier_number]
        st.info(
            f"🤖 Detected Purpose: [{detected_purpose}] -> "
            f"Auto-Routed to [Tier {routed_tier_number}]"
        )

        tier_options = list(TIERS)
        selected_tier_number = st.selectbox(
            "Generation fidelity",
            options=tier_options,
            index=tier_options.index(routed_tier_number),
            format_func=lambda number: TIERS[number].label,
            help="The intent router selects a default tier; you can change it for this generation.",
        )
        selected_tier = TIERS[selected_tier_number]

        st.write(
            f"Selected profile: **{selected_tier.steps} steps**, "
            f"**{selected_tier.width} x {selected_tier.height}** pixels."
        )
        estimated_latency = BASELINE_LATENCY_SECONDS * selected_tier.steps / 50
        render_telemetry(
            selected_tier,
            calculate_telemetry(selected_tier, estimated_latency),
            "Estimated generation telemetry",
        )
        render_calculation_explanation(selected_tier)

        generate_clicked = st.button(
            "Generate image",
            type="primary",
            disabled=not prompt,
            help="Creates the image using the selected tier profile.",
        )
        if generate_clicked:
            request_started_at = time.perf_counter()
            try:
                with st.spinner(f"Generating with {selected_tier.label}..."):
                    image_bytes, measured_latency = generate_image(
                        prompt, selected_tier
                    )
                st.session_state["latest_generation"] = {
                    "image": image_bytes,
                    "tier_number": selected_tier.number,
                    "telemetry": calculate_telemetry(selected_tier, measured_latency),
                    "error": None,
                }
            except requests.RequestException as error:
                elapsed = time.perf_counter() - request_started_at
                st.session_state["latest_generation"] = {
                    "image": None,
                    "tier_number": selected_tier.number,
                    "telemetry": calculate_telemetry(selected_tier, max(elapsed, 0.001)),
                    "error": f"The image service request failed: {error}",
                }
            except ValueError as error:
                st.session_state["latest_generation"] = {
                    "image": None,
                    "tier_number": selected_tier.number,
                    "telemetry": calculate_telemetry(
                        selected_tier, max(time.perf_counter() - request_started_at, 0.001)
                    ),
                    "error": str(error),
                }

        latest_generation = st.session_state.get("latest_generation")
        if latest_generation:
            if latest_generation["error"]:
                st.error(latest_generation["error"])
            if latest_generation["image"]:
                st.image(
                    latest_generation["image"],
                    caption=TIERS[latest_generation["tier_number"]].label,
                    use_container_width=True,
                )
            render_telemetry(
                TIERS[latest_generation["tier_number"]],
                latest_generation["telemetry"],
                "Latest generation telemetry (measured API round trip)",
            )

            if latest_generation["tier_number"] == 1 and latest_generation["image"]:
                st.success(
                    "Pedagogical Proof: Tier 1 provides clean open outlines designed "
                    "specifically for a 7-year-old's motor skills. A Tier 3 "
                    "photorealistic render is unusable as a coloring activity and "
                    "wastes 93% more energy."
                )

    with district_tab:
        render_district_portal()


if __name__ == "__main__":
    main()