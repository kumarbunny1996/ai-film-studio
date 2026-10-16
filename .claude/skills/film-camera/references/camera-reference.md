<!-- Adapted from RobLe3/cc-blender-skill@a2634b588e80265e796aa53f8ab178d75105c2af,
     plugin/skills/blender-cameras/SKILL.md and references/overview.md.
     MIT License, Copyright (c) 2026 RobLe3 (see ../LICENSE).
     Modified for AI Film Studio; see ../UPSTREAM.md. Code recipes removed. -->

# Camera reference

This is background knowledge for planning SceneSpec cameras and writing
schema-gap proposals. Only `blender/scripts/build_scene.py` creates cameras,
from a validated spec.

## Fundamentals

- **Focal length (mm):** lower is wider, higher is tighter.
- **Sensor size:** together with focal length, it sets the field of view. Our
  builder fixes a 36 mm full-frame width. With Blender's automatic sensor fit,
  that width spans the longer side of the frame, which is horizontal for
  landscape renders.
- **Aperture (f-stop):** lower numbers give shallower depth of field.
- **Focus object / distance:** what is tack-sharp. The schema supports a focus
  object in every version, and a focus distance (`focus_distance_m`, used
  only without a focus object) from v1.2.

## Focal length and field of view

Upstream tables quote approximate *diagonal* full-frame angles (50 mm ≈ 46°).
The film-camera skill uses *horizontal* angles for a 36 mm width
(`hfov = 2·atan(18 / f)`): 50 mm ≈ 40°, which is the number that matters for
framing a landscape shot.

| Lens | Horizontal FOV (36 mm) | Use | Feel |
|---|---|---|---|
| 14–24 mm | 104–74° | Architecture, landscapes, tight interiors | Distorted, exaggerated perspective |
| 28–35 mm | 65–54° | Establishing, environments, groups | Natural-wide, documentary |
| 50 mm | 40° | Human-eye perspective | Neutral, cinematic standard |
| 85 mm | 24° | Portraits, character close-ups | Flattering, separates subject |
| 100–135 mm | 20–15° | Hero subjects, isolation | Compressed background, glamour |
| 200 mm+ | ≤10° | Long-lens observation | Heavy compression, very shallow DoF |

## Aperture

| f-stop | Depth of field | Use |
|---|---|---|
| f/1.2 | Razor thin | Macro, dreamy hero portraits |
| f/2.0 | Very shallow | Product hero, character close-up |
| f/2.8 | Shallow | Standard portrait |
| f/4 | Moderate | Two characters both sharp |
| f/5.6 | Medium | Groups, subject in environment |
| f/8 | Deep | Landscape |
| f/16+ | Very deep | Architectural, technical |

## Composition rules worth knowing

1. **Rule of thirds:** put the subject on a third-line intersection, not dead
   centre. `camera.look_at` centres its aim point unless v1.2
   `framing.subject_offset` is set (landscape and square frames only); see
   film-camera.
2. **Leading lines:** roads, walls, edges and light beams lead the eye to the
   subject. Arrange set primitives and props to provide them.
3. **Headroom and nose room:** leave space above the head (about 10% of
   frame height) and in the direction the subject faces or moves.
4. **Foreground / midground / background:** three depth layers create
   dimensionality and parallax on camera moves.
5. **180° rule:** keep screen direction consistent across cuts by keeping
   cameras on one side of the line of action.
6. **Horizon placement:** for landscapes, put the horizon on the lower third
   (sky-led) or upper third (ground-led), rarely in the centre.

## Push-in vs zoom

A push-in (physical move, fixed lens) changes perspective and feels
cinematic. A zoom (lens change, fixed position) keeps perspective and feels
like news or surveillance footage. A dolly-zoom combines them in opposite
directions.

## Sensor sizes (for future schema proposals only)

| Sensor | Width | Notes |
|---|---|---|
| Full frame / 35 mm cinema | 36 mm | Blender default; **the only value our builder uses** |
| Super 35 | 24.89 mm | Most cinema cameras |
| APS-C | 22.5 mm | 1.5–1.6× crop |
| Micro Four Thirds | 17.3 mm | Mirrorless |
| Smartphone (e.g. iPhone 15 Pro) | 9.8 mm | Phone reference |

## Cinematic effects vocabulary (not supported yet)

These all require schema and builder work, plus possibly compositor
templates. List them as gaps when a shot needs them:

- **Anamorphic / scope look:** a 2.39:1 render aspect (`render.resolution`
  can already express this) and an anamorphic bokeh option (not exposed).
- **Lens flare, vignette, film grain:** compositor or post effects.
- **Multi-camera markers within a shot:** not used. One SceneSpec is one
  shot with one camera; cuts happen in the edit stage.
- **Stereo / VR cameras, match-move:** out of scope.
