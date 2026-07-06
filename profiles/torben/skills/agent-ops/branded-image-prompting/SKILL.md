---
name: branded-image-prompting
description: Generate reusable on-brand image prompts and prompt libraries for thumbnails, diagrams, infographics, social images, and mockups. Use for branded or recurring-format image requests, brand-consistent visual prompt generation, or correcting image drift.
---

# Branded Image Prompting

## First-Run Interview

Before generating final brand prompts, ask for:

- Brand colors with hex values.
- Typography direction.
- Overall visual style and reference images if available.
- Common image formats: thumbnails, diagrams, infographics, social images, mockups, covers, or product shots.
- Any banned styles or visual cliches.

If brand identity is missing, create only a draft prompt framework and ask for brand inputs.

## Default Routing

Route actual image generation through Eric's image-gateway skill when available. If no image-gateway skill exists in the active harness, ask whether to use the available image generation tool for this run.

After a prompt succeeds, add it back to the local prompt library or suggest a library update for review. Do not silently overwrite brand rules.

## Prompt-Ready Brand Language

Convert brand inputs into prompt language:

- Color palette: primary, secondary, accent, neutral, background.
- Typography direction: geometric, editorial, technical, monospace, warm, dense, etc.
- Composition: grid, negative space, product-first, diagrammatic, cinematic, editorial, operational.
- Texture and lighting: only if brand-appropriate.
- Avoid list: off-brand colors, stock-photo tropes, fake UI, mangled text, clutter.

## Prompt Patterns

Natural-language prompts work better when the model responds to descriptive art direction:

```text
Create a [format] for [subject]. Use [brand colors] with [composition]. The image should feel [style words]. Include [objects/layout]. Avoid [drift risks]. No small unreadable text.
```

JSON-structured prompts work better when repeatability and slots matter:

```json
{
  "format": "thumbnail",
  "subject": "",
  "palette": {
    "primary": "",
    "secondary": "",
    "accent": "",
    "background": ""
  },
  "composition": "",
  "style": [],
  "required_elements": [],
  "avoid": [],
  "text_policy": "no small text; only large readable title if requested"
}
```

## Starter Prompt Library

Create and adapt templates for:

1. Release briefing thumbnail.
2. Technical concept diagram.
3. Architecture/control-plane diagram.
4. Workflow loop diagram.
5. Social post image.
6. Newsletter header.
7. Product mockup.
8. Before/after comparison.
9. Research note visual.
10. Infographic summary.
11. Failure-mode map.
12. Operator checklist visual.

For each template, preserve slots for subject, audience, brand colors, and output dimensions.

## Corrective Prompting

- Wrong colors: restate hex colors, remove competing color names, specify color proportions.
- Mangled text: remove text from the image or request one large exact phrase only.
- Off-style: name the drift and restate the desired composition in concrete visual terms.
- Too stock-like: specify actual product/state/object/diagram elements and ban generic people-at-laptops imagery.
- Too cluttered: reduce required elements and specify one focal object plus one supporting detail.
- Weak brand signal: increase palette dominance and typography/composition cues.

## Output

Return:

- Natural-language prompt.
- JSON prompt when repeatability matters.
- Drift risks and corrective prompt.
- Suggested library template update if the prompt is reusable.
