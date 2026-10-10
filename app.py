from __future__ import annotations

import html
import random
import re
import time
from dataclasses import dataclass
from io import BytesIO
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
    prefix: str = ""
    suffix: str = ""

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
        prefix=(
            "coloring book page for children, simple black and white line art, "
            "thick crisp outlines of "
        ),
        suffix=(
            ", pure white background, empty fill, zero shading, no grayscale, "
            "no shadows, no watermark, no logo, no text"
        ),
    ),
    2: GenerationTier(
        number=2,
        name="Classroom Vector",
        steps=15,
        width=768,
        height=768,
        suffix=(
            ", flat educational vector illustration, simple bold shapes, "
            "vibrant primary colors, no watermark, no logo"
        ),
    ),
    3: GenerationTier(
        number=3,
        name="District Master Baseline",
        steps=50,
        width=1024,
        height=1024,
        suffix=(
            ", 8k resolution, photorealistic, cinematic lighting, "
            "ultra-detailed official district banner, no watermark, no logo"
        ),
    ),
}

BASELINE_LATENCY_SECONDS = 9.8
BASELINE_ENERGY_WH = 0.816
BASELINE_COST_USD = 0.0049
ACTIVE_POWER_WATTS = 300
INSTANCE_RATE_USD_PER_HOUR = 1.80
GRID_EMISSION_FACTOR_G_PER_WH = 0.82
POLLINATIONS_URL = "https://image.pollinations.ai/prompt/"

DISTRICT_SCHOOLS = 300
DISTRICT_MONTHLY_REQUESTS = 45_000
DISTRICT_NAIVE_SPEND_USD = 1_800.00
DISTRICT_GOVERNED_SPEND_USD = 220.00
DISTRICT_ENERGY_SAVED_KWH = 342
DISTRICT_TIER_SHARES = {1: 0.84, 2: 0.11, 3: 0.05}

CUSTOM_CSS = """
<style>
:root {
    color-scheme: dark;
    --ecocanvas-bg: #0e1117;
    --ecocanvas-surface: #161b22;
    --ecocanvas-border: #30363d;
    --ecocanvas-text: #e0e0e0;
    --ecocanvas-muted: #9ba5b0;
    --ecocanvas-green: #3fb950;
}
html, body, [data-testid="stAppViewContainer"],
[data-testid="stMain"], [data-testid="stHeader"] {
    background-color: var(--ecocanvas-bg);
    color: var(--ecocanvas-text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
[data-testid="stAppViewContainer"] *, [data-testid="stDialog"] * {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
[data-testid="stHeader"] { background: rgba(14, 17, 23, 0.92); }
[data-testid="stForm"] {
    background: var(--ecocanvas-surface);
    border: 1px solid var(--ecocanvas-border);
    border-radius: 12px;
    padding: 1.25rem 1.35rem;
}
[data-testid="stTextArea"] textarea,
[data-testid="stTextInput"] input,
[data-testid="stSelectbox"] [data-baseweb="select"] > div {
    background: #0e1117;
    color: var(--ecocanvas-text);
    border-color: var(--ecocanvas-border);
}
[data-testid="stTabs"] button[role="tab"] { color: var(--ecocanvas-muted); }
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    color: var(--ecocanvas-text);
    border-bottom-color: var(--ecocanvas-green);
}
.eco-bento {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 0.75rem;
    margin: 0.75rem 0 1rem;
}
.eco-metric {
    min-width: 0;
    padding: 0.95rem 1rem;
    background: var(--ecocanvas-surface);
    border: 1px solid var(--ecocanvas-border);
    border-radius: 10px;
}
.eco-metric-label {
    color: var(--ecocanvas-muted);
    font-size: 0.82rem;
    line-height: 1.3;
}
.eco-metric-value {
    margin: 0.45rem 0 0.6rem;
    color: var(--ecocanvas-text);
    font-size: 1.3rem;
    font-weight: 650;
    line-height: 1.2;
    overflow-wrap: anywhere;
}
.eco-delta {
    display: inline-block;
    padding: 0.22rem 0.48rem;
    color: #7ee787;
    background: rgba(46, 160, 67, 0.16);
    border: 1px solid rgba(63, 185, 80, 0.35);
    border-radius: 999px;
    font-size: 0.73rem;
    font-weight: 600;
}
.eco-delta.eco-negative {
    color: #ffb4a9;
    background: rgba(248, 81, 73, 0.12);
    border-color: rgba(248, 81, 73, 0.35);
}
.eco-share-button {
    display: flex;
    box-sizing: border-box;
    min-height: 2.65rem;
    width: 100%;
    align-items: center;
    justify-content: center;
    padding: 0.55rem 0.75rem;
    color: #07150b !important;
    background: #25D366;
    border: 1px solid #25D366;
    border-radius: 0.55rem;
    font-weight: 650;
    text-decoration: none !important;
}
.eco-share-button:hover { background: #20bd5a; border-color: #20bd5a; }
.eco-route-note {
    padding: 0.7rem 0.85rem;
    color: var(--ecocanvas-text);
    background: var(--ecocanvas-surface);
    border: 1px solid var(--ecocanvas-border);
    border-left: 3px solid var(--ecocanvas-green);
    border-radius: 8px;
}
@media (max-width: 760px) {
    .eco-bento { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    [data-testid="stForm"] { padding: 1rem; }
}
</style>
"""


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
    carbon_g = energy_wh * GRID_EMISSION_FACTOR_G_PER_WH
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


def build_telemetry_cards(tier: GenerationTier, telemetry: dict[str, float]) -> str:
    """Return a compact, escaped four-card telemetry grid."""
    cards = (
        ("Latency", telemetry["latency_seconds"], BASELINE_LATENCY_SECONDS, "s", 3),
        ("Energy", telemetry["energy_wh"], BASELINE_ENERGY_WH, "Wh", 6),
        (
            "Carbon",
            telemetry["carbon_g"],
            BASELINE_ENERGY_WH * GRID_EMISSION_FACTOR_G_PER_WH,
            "g CO2e",
            6,
        ),
        ("Cost", telemetry["cost_usd"], BASELINE_COST_USD, "$", 6),
    )
    rendered_cards = []
    for label, value, baseline, unit, precision in cards:
        savings = percentage_savings(baseline, value)
        badge_class = "eco-delta" if savings >= 0 else "eco-delta eco-negative"
        display_value = (
            f"${value:.{precision}f}"
            if label == "Cost"
            else f"{value:.{precision}f} {unit}"
        )
        rendered_cards.append(
            "<div class=\"eco-metric\">"
            f"<div class=\"eco-metric-label\">{html.escape(label)}</div>"
            f"<div class=\"eco-metric-value\">{html.escape(display_value)}</div>"
            f"<span class=\"{badge_class}\">{-savings:+.1f}% vs Tier 3</span>"
            "</div>"
        )
    return "<div class=\"eco-bento\">" + "".join(rendered_cards) + "</div>"


def render_calculation_explanation(tier: GenerationTier) -> None:
    with st.expander("📐 How is this estimate calculated?"):
        st.markdown(
            """
**Hardware and reference assumptions**

- GPU reference: NVIDIA A100 PCIe with a 300 W active TDP.
- Cloud instance rate: $1.80 per hour.
- Tier 3 reference: 9.8 seconds, 0.816 Wh, and $0.0049 per generation.
- India CEA grid factor: 0.82 kg CO2e/kWh, equivalent to 0.82 g CO2e/Wh.

**Per-generation formulas**

- Energy (Wh) = (300 W x latency seconds x (steps / 50) x (width x height / (1024 x 1024))) / 3600.
- Carbon (g CO2e) = energy (Wh) x 0.82 g/Wh.
- Cost (USD) = ($1.80 / 3600) x latency seconds x (steps / 50).
- Savings (%) = ((Tier 3 reference - current estimate) / Tier 3 reference) x 100.

The tier resolution ratio is `(width x height) / (1024 x 1024)`. Before generation,
latency is estimated by scaling the 9.8-second Tier 3 reference by `steps / 50`.
After generation, latency is the measured HTTP request round trip, including the
image download. Because the image service does not expose GPU power telemetry,
energy and carbon remain estimates from the stated A100 model, not direct server
measurements.
"""
        )
        st.caption(
            f"Selected profile: {tier.label}, {tier.steps} steps, "
            f"{tier.width} x {tier.height} pixels."
        )


def generate_image(prompt: str, tier: GenerationTier) -> tuple[Image.Image, float]:
    prompt_text = f"{tier.prefix}{prompt}{tier.suffix}"
    encoded_prompt = quote(prompt_text, safe="")
    seed = random.randint(100_000, 999_999)
    url = (
        f"{POLLINATIONS_URL}{encoded_prompt}"
        f"?width={tier.width}&height={tier.height}&model=flux"
        f"&seed={seed}&nologo=true"
    )

    started_at = time.perf_counter()
    response = requests.get(url, timeout=(10, 120))
    elapsed_seconds = time.perf_counter() - started_at
    response.raise_for_status()
    try:
        with Image.open(BytesIO(response.content)) as source_image:
            image = source_image.convert("RGB")
            image.load()
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("The image service response was not a readable image.") from error
    return image, elapsed_seconds


def image_to_png_bytes(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def render_generated_result() -> None:
    result = st.session_state.get("latest_generation")
    if not result:
        st.markdown(
            "<div class=\"eco-route-note\">Your generated asset and its "
            "environmental estimate will appear here.</div>",
            unsafe_allow_html=True,
        )
        return

    if result["error"]:
        st.error(result["error"])
        return

    tier = TIERS[result["tier_number"]]
    st.markdown(
        "<div class=\"eco-route-note\">"
        f"🤖 Detected Purpose: [{html.escape(result['purpose'])}] &rarr; "
        f"Auto-Routed to [Tier {result['routed_tier_number']}]"
        f"<br><span style=\"color:#9ba5b0\">Generated profile: "
        f"{html.escape(tier.label)}</span></div>",
        unsafe_allow_html=True,
    )
    st.markdown("#### Generated asset")
    image_columns = st.columns([1, 8, 1])
    with image_columns[1]:
        st.image(result["png_bytes"], caption=tier.label, width=380)

    st.markdown("#### Generation telemetry")
    st.markdown(
        build_telemetry_cards(tier, result["telemetry"]),
        unsafe_allow_html=True,
    )

    png_bytes = result["png_bytes"]
    energy_savings = percentage_savings(
        BASELINE_ENERGY_WH, result["telemetry"]["energy_wh"]
    )
    cost_savings = percentage_savings(
        BASELINE_COST_USD, result["telemetry"]["cost_usd"]
    )
    share_message = (
        f"Generated with EcoCanvas! Prompt: {result['prompt']}. "
        f"Energy Saved: {energy_savings:.1f}%. Cost Saved: {cost_savings:.1f}%."
    )
    whatsapp_url = "https://api.whatsapp.com/send?text=" + quote(share_message, safe="")

    download_column, share_column = st.columns([1, 1])
    with download_column:
        st.download_button(
            "⬇️ Download PNG",
            data=png_bytes,
            file_name="ecocanvas-asset.png",
            mime="image/png",
            use_container_width=True,
        )
    with share_column:
        st.markdown(
            f'<a class="eco-share-button" href="{html.escape(whatsapp_url, quote=True)}" '
            'target="_blank" rel="noopener noreferrer">Share on WhatsApp</a>',
            unsafe_allow_html=True,
        )

    if result["tier_number"] == 1:
        st.success(
            "Pedagogical Proof: Tier 1 provides clean open outlines designed "
            "specifically for a 7-year-old's motor skills. A Tier 3 photorealistic "
            "render is unusable as a coloring activity and wastes 93% more energy."
        )


def render_district_portal() -> None:
    st.header("🏢 District FinOps Portal (300 Schools)")
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
    breakdown = []
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
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    st.title("EcoCanvas")
    st.caption("Right-sized educational image generation for district classrooms")

    classroom_tab, district_tab = st.tabs(
        ["🎨 Classroom Generator", "🏢 District FinOps Portal (300 Schools)"]
    )

    with classroom_tab:
        left_column, right_column = st.columns([1, 1], gap="large")
        with left_column:
            st.subheader("Create a classroom asset")
            with st.form(key="gen_form", clear_on_submit=False):
                prompt = st.text_area(
                    "Describe the image",
                    placeholder="For example: An elephant for a kids' coloring worksheet",
                    max_chars=500,
                    height=135,
                ).strip()
                routed_tier_number, detected_purpose = classify_prompt(prompt)
                tier_choices = [
                    ("Auto-route (recommended)", None),
                    ("Tier 1 - Eco-Outline", 1),
                    ("Tier 2 - Classroom Vector", 2),
                    ("Tier 3 - District Master Baseline", 3),
                ]
                selected_choice = st.radio(
                    "Fidelity profile",
                    options=[choice[0] for choice in tier_choices],
                    index=0,
                    help="Auto-route chooses the lowest-cost tier suggested by your prompt.",
                )
                generate_clicked = st.form_submit_button(
                    "⚡ Generate Asset",
                    type="primary",
                    use_container_width=True,
                )

            if generate_clicked:
                if not prompt:
                    st.session_state["latest_generation"] = {
                        "error": "Enter a prompt before generating an asset."
                    }
                else:
                    selected_tier_number = next(
                        tier_number
                        for label, tier_number in tier_choices
                        if label == selected_choice
                    )
                    tier_number = selected_tier_number or routed_tier_number
                    tier = TIERS[tier_number]
                    started_at = time.perf_counter()
                    try:
                        with st.spinner(f"Generating with {tier.label} using Flux..."):
                            image, request_latency = generate_image(prompt, tier)
                            png_bytes = image_to_png_bytes(image)
                        st.session_state["latest_generation"] = {
                            "error": None,
                            "prompt": prompt,
                            "image": image,
                            "png_bytes": png_bytes,
                            "tier_number": tier.number,
                            "routed_tier_number": routed_tier_number,
                            "purpose": detected_purpose,
                            "telemetry": calculate_telemetry(tier, request_latency),
                        }
                    except requests.RequestException as error:
                        st.session_state["latest_generation"] = {
                            "error": f"The image service request failed: {error}"
                        }
                    except ValueError as error:
                        st.session_state["latest_generation"] = {"error": str(error)}

            tier_for_explanation = TIERS[
                st.session_state.get("latest_generation", {}).get(
                    "tier_number", routed_tier_number
                )
            ]
            render_calculation_explanation(tier_for_explanation)

        with right_column:
            render_generated_result()

    with district_tab:
        render_district_portal()


if __name__ == "__main__":
    main()
