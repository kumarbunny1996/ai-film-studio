"""
mannequin.py — author the homemade low-poly mannequin character, its actions and a prop.

Run headless, with no template, add-ons or network access:

    blender -b --factory-startup --python-exit-code 1 \
        -P blender/scripts/author_assets/mannequin.py -- --out-root <dir> [--set m7] [--force]

Writes, under --out-root (the same layout as assets/):
    characters/mannequin.blend       collection CH-mannequin: RIG-mannequin + GEO-mannequin
    actions/mannequin_actions.blend  actions mannequin_idle (48 frames), mannequin_walk (32)
    props/mannequin_baton.blend      collection PR-mannequin_baton: GEO-mannequin_baton

and with --set m7 (Milestone 7) instead:
    characters/mannequin_ochre.blend collection CH-mannequin_ochre: RIG-/GEO-mannequin_ochre
    actions/mannequin_gestures.blend actions mannequin_look (24 frames), mannequin_wave (60)

and with --set m11 (Milestone 11) instead, both characters with head marker A (MARKER_A):
    characters/mannequin_marked.blend        collection CH-mannequin_marked
    characters/mannequin_ochre_marked.blend  collection CH-mannequin_ochre_marked

If any file of the chosen set exists, nothing is written unless --force is given. Files are
written to *.tmp.blend first and then moved into place, so a failed run never leaves a
truncated asset.

Conventions (rig_type afs_mannequin_v1):
  * 1.75 m tall, origin on the ground between the feet, facing -Y, Z up, arms in a 20° A-pose.
  * 17 bones (BONES below); pose bones use XYZ Euler. Each body part is rigidly weighted (1.0)
    to one bone through an Armature modifier, and the mesh is parented to the armature.
  * hand.L / hand.R tails are the grip points: Blender bone parenting attaches at the tail.
  * Actions are in place (travel comes from SceneSpec motion_path), keyed on integer frames,
    one OBJECT slot each, with a manual frame range whose last key repeats the first, so NLA
    repeats loop without a pop. Both actions key the same channels (every bone's
    rotation_euler plus the hips location), so a REPLACE crossfade never leaves a channel
    from the previous clip behind.
  * Walk (keyed on every frame; cycle R1S, 0.538 m steps): each leg is in stance for half the
    cycle on a footprint that moves back at exactly WALK_M_PER_FRAME, so with matching root
    travel the planted foot is stationary; heels land at CONTACT. The foot is flat (ankle on
    its rest height) until WALK_Q_HEEL, then the heel rises and the toe is the contact point
    until toe-off. The pelvis sinks into each heel strike and rises over the stance leg
    (walk_pelvis), yaws +-3 deg with the chest counter-rotating, and the head keeps the gaze
    forward. The swing is a joint-space Hermite with zero world foot speed at both ends, the
    foot passing under the hips at mid-swing, and a short terminal descent onto the heel. At
    phase 0.5 (frame 17) the left foot is flat under the hips at mid-stance with no yaw and the
    right foot is in the air directly under the hips: ending a walk clip there and
    crossfading into idle stops the character without sliding.
  * Idle (keyed every 6 frames): breathing in the spine, chest, head and arms; both legs stand
    still on the walk's frame-17 stance leg (soft knee, hips slightly lowered), so the walk ->
    idle crossfade leaves the planted leg unchanged and sets the swing foot straight down.
  * Gestures (Milestone 7, keyed every frame, not loopable) key only the channels they move,
    to be layered over a continuous idle on a higher NLA track: mannequin_look turns the
    spine, chest, neck and head (Y rotation only) 40 deg to the character's right and holds;
    mannequin_wave raises the right arm, swings the forearm side to side twice and lowers it
    back to the idle's mean arm pose. Neither keys the legs or the hips.

The pose tables (everything above `import bpy`) are plain Python so tests can check them
without Blender.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

RIG_TYPE = "afs_mannequin_v1"
CHARACTER_FILE = Path("characters/mannequin.blend")
ACTIONS_FILE = Path("actions/mannequin_actions.blend")
PROP_FILE = Path("props/mannequin_baton.blend")
OUTPUTS = (CHARACTER_FILE, ACTIONS_FILE, PROP_FILE)
# Milestone 7 set (--set m7): an ochre variant of the character and the gesture actions. The
# Milestone 6 set above is unchanged and written only by --set m6 (the default).
OCHRE_FILE = Path("characters/mannequin_ochre.blend")
GESTURES_FILE = Path("actions/mannequin_gestures.blend")
M7_OUTPUTS = (OCHRE_FILE, GESTURES_FILE)
# Milestone 11 set (--set m11): both characters with head marker A, as new assets under their
# own names. The m6 and m7 sets are unchanged.
MARKED_FILE = Path("characters/mannequin_marked.blend")
OCHRE_MARKED_FILE = Path("characters/mannequin_ochre_marked.blend")
M11_OUTPUTS = (MARKED_FILE, OCHRE_MARKED_FILE)

CHARACTER_COLLECTION, ARMATURE, BODY = "CH-mannequin", "RIG-mannequin", "GEO-mannequin"
PROP_COLLECTION, PROP_OBJECT = "PR-mannequin_baton", "GEO-mannequin_baton"
MATERIALS = {"body": ("MAT-mannequin_body", (0.62, 0.60, 0.56)),
             "accent": ("MAT-mannequin_accent", (0.12, 0.28, 0.55)),
             "baton": ("MAT-mannequin_baton", (0.30, 0.18, 0.09)),
             "ochre_body": ("MAT-mannequin_ochre_body", (0.60, 0.30, 0.05)),
             "ochre_accent": ("MAT-mannequin_ochre_accent", (0.25, 0.07, 0.03)),
             "marker": ("MAT-mannequin_marker", (0.03, 0.03, 0.035)),
             "ochre_marker": ("MAT-mannequin_ochre_marker", (0.03, 0.03, 0.035))}
ROUGHNESS, MARKER_ROUGHNESS = 0.6, 0.35            # every material is 0.6 except the markers
MATERIAL_ROUGHNESS = {"marker": MARKER_ROUGHNESS, "ochre_marker": MARKER_ROUGHNESS}
# The ochre variant: the same skeleton, body parts and rig type under its own names, so both
# characters can share a scene and every afs_mannequin_v1 action plays on either.
OCHRE = {"collection": "CH-mannequin_ochre", "armature": "RIG-mannequin_ochre",
         "body": "GEO-mannequin_ochre", "materials": ("ochre_body", "ochre_accent")}
# The marked variants (Milestone 11): the same characters with head marker A, under their own
# names; material slot 2 is the marker.
MARKED = {"collection": "CH-mannequin_marked", "armature": "RIG-mannequin_marked",
          "body": "GEO-mannequin_marked", "materials": ("body", "accent", "marker")}
OCHRE_MARKED = {"collection": "CH-mannequin_ochre_marked", "armature": "RIG-mannequin_ochre_marked",
                "body": "GEO-mannequin_ochre_marked",
                "materials": ("ochre_body", "ochre_accent", "ochre_marker")}

# ---------------------------------------------------------------------------
# Skeleton: name -> (parent, head, tail, connected). Metres, facing -Y.
# ---------------------------------------------------------------------------
_ARM_DIR = (math.sin(math.radians(20)), 0.0, -math.cos(math.radians(20)))   # A-pose, left side


def _along(p, d, length):
    return tuple(round(p[i] + d[i] * length, 6) + 0.0 for i in range(3))


def _skeleton() -> dict[str, tuple]:
    bones = {
        "hips":  (None,    (0, 0, 0.95), (0, 0, 1.05), False),
        "spine": ("hips",  (0, 0, 1.05), (0, 0, 1.25), True),
        "chest": ("spine", (0, 0, 1.25), (0, 0, 1.45), True),
        "neck":  ("chest", (0, 0, 1.45), (0, 0, 1.55), True),
        "head":  ("neck",  (0, 0, 1.55), (0, 0, 1.75), True),
    }
    for side, sx in (("L", 1.0), ("R", -1.0)):
        d = (sx * _ARM_DIR[0], 0.0, _ARM_DIR[2])
        shoulder = (sx * 0.18, 0.0, 1.42)
        elbow = _along(shoulder, d, 0.28)
        wrist = _along(elbow, d, 0.26)
        bones[f"upper_arm.{side}"] = ("chest", shoulder, elbow, False)
        bones[f"forearm.{side}"] = (f"upper_arm.{side}", elbow, wrist, True)
        bones[f"hand.{side}"] = (f"forearm.{side}", wrist, _along(wrist, d, 0.10), True)
        bones[f"thigh.{side}"] = ("hips", (sx * 0.10, 0, 0.95), (sx * 0.10, 0, 0.50), False)
        bones[f"shin.{side}"] = (f"thigh.{side}", (sx * 0.10, 0, 0.50), (sx * 0.10, 0, 0.08), True)
        bones[f"foot.{side}"] = (f"shin.{side}", (sx * 0.10, 0, 0.08),
                                 (sx * 0.10, -0.15, 0.045), True)   # sole at z 0
    return {n: (p, tuple(float(c) for c in h), tuple(float(c) for c in t), con)
            for n, (p, h, t, con) in bones.items()}


BONES = _skeleton()
THIGH_M = BONES["thigh.L"][1][2] - BONES["thigh.L"][2][2]       # 0.45
SHIN_M = BONES["shin.L"][1][2] - BONES["shin.L"][2][2]          # 0.42

# Body parts: bone -> (shape, dims, material). "cyl" spans the bone with radius dims[0];
# "box" is centred on the bone's midpoint with size dims; "ball" is centred on the midpoint.
PARTS = {
    "hips": ("box", (0.32, 0.18, 0.16), "body"),
    "spine": ("box", (0.27, 0.15, 0.20), "body"),
    "chest": ("box", (0.38, 0.20, 0.22), "body"),
    "neck": ("cyl", (0.045,), "body"),
    "head": ("ball", (0.10,), "body"),
    **{f"{part}.{side}": spec for side in ("L", "R") for part, spec in (
        ("upper_arm", ("cyl", (0.045,), "body")), ("forearm", ("cyl", (0.040,), "body")),
        ("hand", ("cyl", (0.035,), "accent")), ("thigh", ("cyl", (0.070,), "body")),
        ("shin", ("cyl", (0.055,), "body")), ("foot", ("cyl", (0.045,), "accent")))},
}
# Head marker A (adopted in Milestone 11; docs/m11_readable_attention.md): part -> (box centre,
# box size (x, y, z), material role), in the rest frame (metres, facing -Y), all rigidly
# weighted to the head bone. The visor is the marker material; the nose is the body material.
MARKER_A = {
    "visor": ((0.0, -0.085, 1.67), (0.13, 0.05, 0.035), "marker"),
    "nose": ((0.0, -0.115, 1.625), (0.035, 0.05, 0.04), "body"),
}
MARKER_BONE = "head"
MATERIAL_SLOT = {"body": 0, "accent": 1, "marker": 2}

# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
# Sign of an X rotation that swings a downward-pointing limb forward (-Y). With roll 0 the
# limb bones' local X is world +X and local Z is world +Y, so +X rotation swings the tail
# backward: FORWARD is -1. Pinned by tests/test_mannequin_assets.py on the evaluated rig.
FORWARD = -1.0
WALK = {"name": "mannequin_walk", "frames": 32, "step": 1}
IDLE = {"name": "mannequin_idle", "frames": 48, "step": 6}
WALK_ARM_DEG, ELBOW_DEG = 11.0, 15.0
LEG_M = THIGH_M + SHIN_M
CONTACT = {"L": 0.25, "R": 0.75}                        # phase at which each heel lands

# Walk cycle R1S (Milestone 6 walk refinement): loading-response pelvis, heel rise, swing foot
# under the hips at mid-swing so a walk can stop at mid-stance without sliding. Sagittal gait
# model, forward = +x relative to the hips, z up, metres and degrees.
WALK_CONTACT_DEG = 18.0       # leading-leg angle at heel strike: sets the step length
WALK_KNEE_CONTACT_DEG = 12.0  # knee flexion when the heel lands
WALK_KNEE_MID_DEG = 5.0       # knee flexion at mid-stance (pelvis high point)
WALK_Q_HEEL = 0.35            # phase since contact at which the heel starts to rise
WALK_HEEL_OFF_DEG = 20.0      # toe-down foot pitch at toe-off
WALK_KNEE_BUMP_DEG = 15.0     # swing knee-flexion bump (clearance)
WALK_TOE_BUMP_DEG = 25.0      # swing dorsiflexion bump (toe clearance)
WALK_CLEAR_M = 0.03           # swing ankle clearance curve: rest + WALK_CLEAR_M sin^2(pi t)
WALK_TOE_CLEAR_M = 0.015      # swing toe kept this far above its rest height
WALK_SOFT_M = 0.01            # softness of the clearance max (fades to 0 at both ends)
WALK_LAND_M = 0.035           # terminal descent onto the heel: + WALK_LAND_M 4 t^2 (1 - t)
WALK_PELVIS_YAW_DEG = 3.0     # pelvis yaw, lead hip forward
WALK_CHEST_YAW_DEG = 3.0      # chest counter-rotation, anti-phase to the pelvis

STEP_HALF_M = LEG_M * math.sin(math.radians(WALK_CONTACT_DEG))   # ankle ahead of the hip at contact
WALK_M_PER_FRAME = 4 * STEP_HALF_M / WALK["frames"]      # two steps of 2 * STEP_HALF_M
HIP_Z = BONES["hips"][1][2]                              # 0.95
ANKLE_Z = BONES["shin.L"][2][2]                          # 0.08, ankle rest height
TOE_Z = BONES["foot.L"][2][2]                            # 0.045, toe (foot tail) rest height
_FOOT = (-(BONES["foot.L"][2][1] - BONES["foot.L"][1][1]), BONES["foot.L"][2][2] - BONES["foot.L"][1][2])
FOOT_LEN = math.hypot(*_FOOT)                            # ankle -> toe, 0.154 m
FOOT_TILT = math.atan2(-_FOOT[1], _FOOT[0])              # rest toe-down tilt, 13.1 deg


def _r(v: float) -> float:
    return round(v, 6) + 0.0                                  # + 0.0 turns -0.0 into 0.0


def ankle_drop(thigh_fwd_deg: float, knee_flex_deg: float) -> float:
    """Vertical hip-to-ankle distance of a leg in the sagittal plane: the thigh swings
    forward by thigh_fwd, the shin flexes backward from it by knee_flex."""
    a, b = math.radians(thigh_fwd_deg), math.radians(knee_flex_deg)
    return THIGH_M * math.cos(a) + SHIN_M * math.cos(a - b)


def _rest_pose() -> dict:
    return {"rot": {b: [0.0, 0.0, 0.0] for b in BONES}, "hips_loc": [0.0, 0.0, 0.0]}


def leg_ik(forward: float, drop: float) -> tuple[float, float]:
    """(thigh forward angle, knee flexion) in degrees that put the ankle `forward` metres
    ahead of and `drop` metres below the hip joint, with the knee bending backward."""
    d = math.hypot(forward, drop)
    if d > LEG_M * (1 + 1e-9):
        raise ValueError(f"ankle target {d:.6f} m from the hip is out of reach ({LEG_M} m)")
    d = min(d, LEG_M)
    cos_b = (d * d - THIGH_M ** 2 - SHIN_M ** 2) / (2 * THIGH_M * SHIN_M)
    cos_alpha = (THIGH_M ** 2 + d * d - SHIN_M ** 2) / (2 * THIGH_M * d)
    b = math.acos(max(-1.0, min(1.0, cos_b)))
    alpha = math.acos(max(-1.0, min(1.0, cos_alpha)))
    return math.degrees(math.atan2(forward, drop) + alpha), math.degrees(b)


def leg_len(knee_deg: float) -> float:
    """Hip-to-ankle distance of a leg with the given knee flexion."""
    return math.sqrt(THIGH_M * THIGH_M + SHIN_M * SHIN_M
                     + 2 * THIGH_M * SHIN_M * math.cos(math.radians(knee_deg)))


def _smooth_max(x: float, y: float, k: float) -> float:
    """max(x, y) smoothed over k (exact max when k == 0)."""
    if k <= 0:
        return max(x, y)
    m = max(x, y)
    return m + k * math.log(math.exp((x - m) / k) + math.exp((y - m) / k))


def _hermite(p0: float, v0: float, p1: float, v1: float, t: float) -> float:
    t2, t3 = t * t, t * t * t
    return ((2 * t3 - 3 * t2 + 1) * p0 + (t3 - 2 * t2 + t) * v0
            + (-2 * t3 + 3 * t2) * p1 + (t3 - t2) * v1)


# Pelvis (hips height relative to rest) at heel strike, where the leading leg reaches its
# footprint with WALK_KNEE_CONTACT_DEG flexion, and at mid-stance over a WALK_KNEE_MID_DEG knee.
WALK_H_CONTACT = (math.sqrt(leg_len(WALK_KNEE_CONTACT_DEG) ** 2 - STEP_HALF_M * STEP_HALF_M)
                  + ANKLE_Z - HIP_Z)
WALK_H_MID = leg_len(WALK_KNEE_MID_DEG) + ANKLE_Z - HIP_Z


def walk_root(p: float) -> float:
    """Hips travel at cycle phase p (unwrapped): one cycle = 4 * STEP_HALF_M."""
    return 4 * STEP_HALF_M * p


def walk_pelvis(p: float) -> float:
    """Loading-response pelvis height per step (phi = 0 at heel strike, 0.5 at mid-stance):
    raised-cosine segments joined with zero slope, low at the strike and high at mid-stance,
    so the pelvis sinks into each heel strike and rises over the stance leg."""
    phi = ((p - 0.25) % 0.5) / 0.5
    s = phi / 0.5 if phi <= 0.5 else (1.0 - phi) / 0.5
    return WALK_H_CONTACT + (WALK_H_MID - WALK_H_CONTACT) * (1 - math.cos(math.pi * s)) / 2


def walk_pelvis_yaw(p: float) -> float:
    return -WALK_PELVIS_YAW_DEG * math.sin(2 * math.pi * p)


def _heel_pitch(q: float) -> float:
    """Toe-down foot pitch (rad) of a stance foot, q in [0, 0.5) after contact: flat until
    WALK_Q_HEEL, then the heel rises (eases in) until toe-off."""
    if q <= WALK_Q_HEEL:
        return 0.0
    u = (q - WALK_Q_HEEL) / (0.5 - WALK_Q_HEEL)
    return math.radians(WALK_HEEL_OFF_DEG) * u * u


def walk_stance_foot(p: float, q: float) -> tuple[float, float, float]:
    """Ankle (forward, height) and foot pitch (rad, toe-down) of a stance leg at q in [0, 0.5).
    The footprint is fixed in the world; while the heel rises the foot pitches about the toe,
    which stays on its rest height."""
    ankle_x0 = walk_root(p - q) + STEP_HALF_M                     # footprint (ankle when flat)
    th = _heel_pitch(q)
    if th == 0.0:
        return ankle_x0, ANKLE_Z, 0.0
    toe_x = ankle_x0 + FOOT_LEN * math.cos(FOOT_TILT)
    b = FOOT_TILT + th
    return toe_x - FOOT_LEN * math.cos(b), TOE_Z + FOOT_LEN * math.sin(b), th


# 3D hips -> thigh -> shin chain in armature space, reproducing Blender's pose evaluation
# pose(bone) = pose(parent) @ inv(rest(parent)) @ rest(bone) @ T(location) @ R(euler XYZ),
# so a planted foot stays exact while the pelvis yaws (the hip joints move).
def _m4(rot, pos=(0.0, 0.0, 0.0)):
    return [[rot[0][0], rot[0][1], rot[0][2], pos[0]], [rot[1][0], rot[1][1], rot[1][2], pos[1]],
            [rot[2][0], rot[2][1], rot[2][2], pos[2]], [0.0, 0.0, 0.0, 1.0]]


def _mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _inv_rigid(m):
    r = [[m[j][i] for j in range(3)] for i in range(3)]
    t = [-sum(r[i][k] * m[k][3] for k in range(3)) for i in range(3)]
    return _m4(r, t)


def _euler_xyz(xd, yd, zd):
    x, y, z = (math.radians(v) for v in (xd, yd, zd))
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    rx = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    ry = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    rz = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]
    m3 = lambda a, b: [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return m3(rz, m3(ry, rx))


def _cols(x, y, z):
    return [[x[0], y[0], z[0]], [x[1], y[1], z[1]], [x[2], y[2], z[2]]]


_UP, _DOWN = _cols((1, 0, 0), (0, 0, 1), (0, -1, 0)), _cols((1, 0, 0), (0, 0, -1), (0, 1, 0))
_REST = {"hips": _m4(_UP, (0, 0, HIP_Z))}
for _side, _sx in (("L", 1.0), ("R", -1.0)):
    _REST[f"thigh.{_side}"] = _m4(_DOWN, (0.1 * _sx, 0, HIP_Z))
    _REST[f"shin.{_side}"] = _m4(_DOWN, (0.1 * _sx, 0, BONES["shin.L"][1][2]))


def leg_fk(side, hips_rot, hips_loc, thigh_rot, shin_rot):
    """Armature-space positions of the hip joint, knee and ankle."""
    local = lambda rot, loc=(0.0, 0.0, 0.0): _m4(_euler_xyz(*rot), loc)
    ph = _mul(_REST["hips"], local(hips_rot, hips_loc))
    pt = _mul(_mul(ph, _inv_rigid(_REST["hips"])), _mul(_REST[f"thigh.{side}"], local(thigh_rot)))
    ps = _mul(_mul(pt, _inv_rigid(_REST[f"thigh.{side}"])), _mul(_REST[f"shin.{side}"], local(shin_rot)))
    tip = lambda m, length: [m[i][1] * length + m[i][3] for i in range(3)]
    return [pt[i][3] for i in range(3)], tip(pt, THIGH_M), tip(ps, SHIN_M)


def _solve3(A, y):
    m = [row[:] + [y[i]] for i, row in enumerate(A)]
    for c in range(3):
        piv = max(range(c, 3), key=lambda r: abs(m[r][c]))
        m[c], m[piv] = m[piv], m[c]
        for r in range(3):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [m[r][k] - f * m[c][k] for k in range(4)]
    return [m[i][3] / m[i][i] for i in range(3)]


def leg_ik_3d(side, yaw_deg, hips_h, target, guess):
    """Thigh forward angle a, knee flexion b and abduction g (degrees) that put the ankle at
    the armature-space target, with the thigh counter-yawed by yaw_deg (cancelling the hips
    yaw in the leg's orientation). Newton iteration with a numeric Jacobian."""
    a, b, g = guess
    F = FORWARD

    def ankle(a, b, g):
        return leg_fk(side, (0.0, yaw_deg, 0.0), (0.0, hips_h, 0.0), (F * a, yaw_deg, g), (-F * b, 0.0, 0.0))[2]

    for _ in range(30):
        r = [ankle(a, b, g)[i] - target[i] for i in range(3)]
        if max(abs(x) for x in r) < 1e-12:
            break
        h = 1e-6
        J = []
        for da, db, dg in ((h, 0, 0), (0, h, 0), (0, 0, h)):
            pt = ankle(a + da, b + db, g + dg)
            J.append([(pt[i] - (r[i] + target[i])) / h for i in range(3)])
        x = _solve3([[J[c][i] for c in range(3)] for i in range(3)], [-v for v in r])
        a, b, g = a + x[0], b + x[1], g + x[2]
    else:
        raise ValueError(f"3D leg IK did not converge for {side} (residual {max(abs(x) for x in r):.2e})")
    if b < 0:
        raise ValueError(f"3D leg IK hyperextends the {side} knee ({b:.3f} deg)")
    return a, b, g


def _stance_joints(p, q, side):
    """(thigh, knee, pitch rad, abduction) of a stance leg on its planted foot."""
    x, z, th = walk_stance_foot(p, q)
    a, b = leg_ik(x - walk_root(p), HIP_Z + walk_pelvis(p) - z)
    yaw = walk_pelvis_yaw(p)
    if yaw == 0.0:
        return a, b, th, 0.0
    sx = 1.0 if side == "L" else -1.0
    a, b, g = leg_ik_3d(side, yaw, walk_pelvis(p), (0.1 * sx, -(x - walk_root(p)), z), (a, b, 0.0))
    return a, b, th, g


def _swing_forward_raw(p, q, side):
    """Ankle ahead of the hips from the swing's joint-space Hermite and bumps alone (the
    clearance lift keeps it)."""
    a, b = _swing_joints(p, q, side, raw=True)
    ar, br = math.radians(a), math.radians(b)
    return THIGH_M * math.sin(ar) + SHIN_M * math.sin(ar - br)


def _swing_joints(p, q, side, raw=False):
    """Joint-space swing, q in [0.5, 1): cubic Hermite in (thigh, knee, pitch, abduction) from
    the toe-off state to the heel-strike state with the stance joint rates at both ends (the
    foot leaves and lands with zero world speed), plus knee and dorsiflexion bumps; then the
    ankle is lifted onto a smooth clearance curve that ends in a terminal descent onto the heel
    (WALK_LAND_M), and the toe-down pitch is limited for toe clearance. The Hermite alone leaves
    the mid-swing ankle behind the hips; a forward shift 64 t^3 (1 - t)^3 (zero value, slope and
    curvature at lift-off and contact) brings it under the hips at mid-swing, so a walk ending
    at mid-stance (cycle frame 17) can set the swing foot straight down into the idle."""
    eps = 1e-5
    t = (q - 0.5) / (1.0 - 0.5)
    p_off, p_on = p - (q - 0.5), p + (1.0 - q)      # phases at toe-off and next contact
    j0 = _stance_joints(p_off, 0.5, side)
    j0m = _stance_joints(p_off - eps, 0.5 - eps, side)
    j1 = _stance_joints(p_on, 0.0, side)
    j1p = _stance_joints(p_on + eps, eps, side)
    dqdt = 1.0 - 0.5
    out = []
    for i in range(4):
        r0 = (j0[i] - j0m[i]) / eps * dqdt
        r1 = (j1p[i] - j1[i]) / eps * dqdt
        out.append(_hermite(j0[i], r0, j1[i], r1, t))
    bump = 16 * t * t * (1 - t) ** 2
    a, b = out[0], out[1] + WALK_KNEE_BUMP_DEG * bump
    th = out[2] - math.radians(WALK_TOE_BUMP_DEG) * bump
    if raw:
        return a, b
    ar, br = math.radians(a), math.radians(b)
    fx = THIGH_M * math.sin(ar) + SHIN_M * math.sin(ar - br)
    drop = THIGH_M * math.cos(ar) + SHIN_M * math.cos(ar - br)
    hip_z = HIP_Z + walk_pelvis(p)
    z = hip_z - drop
    k = WALK_SOFT_M * 4 * t * (1 - t)
    z_req = ANKLE_Z + WALK_CLEAR_M * math.sin(math.pi * t) ** 2 + WALK_LAND_M * 4 * t * t * (1 - t)
    z_new = _smooth_max(z, z_req, k)
    lag = _swing_forward_raw(p + (0.75 - q), 0.75, side)        # at mid-swing (t = 0.5)
    shift = -1.0 * lag * 64 * t ** 3 * (1 - t) ** 3
    if z_new != z or shift:
        a, b = leg_ik(fx + shift, hip_z - z_new)  # raising the ankle only shortens the reach
        z = z_new
    toe_req = TOE_Z + WALK_TOE_CLEAR_M * math.sin(math.pi * t) ** 2
    room = (z - toe_req) / FOOT_LEN               # toe z = ankle z - FOOT_LEN sin(tilt + th)
    th_max = math.asin(max(-1.0, min(1.0, room))) - FOOT_TILT
    th = -_smooth_max(-th, -th_max, math.radians(10) * 4 * t * (1 - t))
    if b < 0:
        raise ValueError(f"swing knee hyperextends ({b:.2f} deg) at q={q:.4f}")
    return a, b, th, out[3]


def walk_leg(p: float, side: str) -> dict:
    q = (p - CONTACT[side]) % 1.0
    stance = q < 0.5
    a, b, th, g = _stance_joints(p, q, side) if stance else _swing_joints(p, q, side)
    return {"q": q, "stance": stance, "a": a, "b": b, "pitch": th, "g": g}


def walk_pose(p: float) -> dict:
    """Pose at phase p in [0, 1): one cycle = two steps. At p=0 the left leg is mid-swing.

    Each leg is in stance for the half cycle after its CONTACT phase (planted footprint, heel
    rising from WALK_Q_HEEL so the toe is the contact point until toe-off) and in swing for the
    other half. The pelvis follows walk_pelvis and yaws with walk_pelvis_yaw; the chest
    counter-rotates in anti-phase, the neck follows the chest and the head turns back so the
    gaze stays forward."""
    pose = _rest_pose()
    h = walk_pelvis(p)
    s2 = math.sin(2 * math.pi * p)
    yaw = walk_pelvis_yaw(p)
    for side, sign in (("L", 1.0), ("R", -1.0)):
        lg = walk_leg(p, side)
        a, b, th = lg["a"], lg["b"], math.degrees(lg["pitch"])
        pose["rot"][f"thigh.{side}"][0] = FORWARD * a
        if yaw != 0.0:
            pose["rot"][f"thigh.{side}"][1] = yaw          # cancels the hips yaw in the leg
            pose["rot"][f"thigh.{side}"][2] = lg["g"]
        pose["rot"][f"shin.{side}"][0] = -FORWARD * b
        pose["rot"][f"foot.{side}"][0] = FORWARD * (b - a - th)   # level, then toe-down th
        pose["rot"][f"upper_arm.{side}"][0] = -FORWARD * sign * WALK_ARM_DEG * s2
        pose["rot"][f"forearm.{side}"][0] = FORWARD * ELBOW_DEG
    chest = WALK_CHEST_YAW_DEG * s2                # world yaws: pelvis, chest, spine midway
    spine = (yaw + chest) / 2
    pose["rot"]["hips"][1] = yaw
    pose["rot"]["spine"][1] = spine - yaw
    pose["rot"]["chest"][1] = chest - spine
    pose["rot"]["neck"][1] = 0.0                   # the neck follows the chest
    pose["rot"]["head"][1] = 0.0 - chest           # head world yaw 0: gaze forward
    # hips bone points up (+Z), so its local Y is world up
    pose["hips_loc"][1] = h
    return pose


# Idle stance = the walk's held mid-stance leg (cycle frame 17: foot flat under the hips, soft
# WALK_KNEE_MID_DEG knee, hips at walk_pelvis(0.5)), on both legs. A walk clip that ends there
# crossfades into the idle without the planted leg changing at all, so the foot cannot drift.
IDLE_THIGH_DEG, IDLE_KNEE_DEG = _stance_joints(0.5, 0.25, "L")[:2]
IDLE_HIPS_M = walk_pelvis(0.5)


def idle_pose(p: float) -> dict:
    pose = _rest_pose()
    s, c = math.sin(2 * math.pi * p), math.cos(2 * math.pi * p)
    pose["rot"]["spine"][0] = 0.5 * s
    pose["rot"]["chest"][0] = 1.5 * s
    pose["rot"]["head"][0] = -1.0 * s
    for side in ("L", "R"):
        pose["rot"][f"upper_arm.{side}"][0] = 1.0 * c
        pose["rot"][f"forearm.{side}"][0] = FORWARD * ELBOW_DEG
        pose["rot"][f"thigh.{side}"][0] = FORWARD * IDLE_THIGH_DEG
        pose["rot"][f"shin.{side}"][0] = -FORWARD * IDLE_KNEE_DEG
        pose["rot"][f"foot.{side}"][0] = FORWARD * (IDLE_KNEE_DEG - IDLE_THIGH_DEG)   # foot flat
    pose["hips_loc"][1] = IDLE_HIPS_M
    return pose                                     # legs and hips still: feet stay planted


def key_table(pose_fn, frames: int, step: int) -> list[tuple[int, dict]]:
    """(frame, pose) keys from frame 1 to 1 + frames inclusive. The last key is computed
    from the same phase as the first (k % frames), so the loop closes exactly."""
    if frames % step:
        raise ValueError(f"{frames} frames is not a multiple of the key step {step}")
    out = []
    for k in range(0, frames + 1, step):
        pose = pose_fn((k % frames) / frames)
        out.append((1 + k, {"rot": {b: [_r(v) for v in r] for b, r in pose["rot"].items()},
                            "hips_loc": [_r(v) for v in pose["hips_loc"]]}))
    return out


def actions() -> dict[str, list[tuple[int, dict]]]:
    return {WALK["name"]: key_table(walk_pose, WALK["frames"], WALK["step"]),
            IDLE["name"]: key_table(idle_pose, IDLE["frames"], IDLE["step"])}


ACTION_FRAMES = {WALK["name"]: WALK["frames"], IDLE["name"]: IDLE["frames"]}


# ---------------------------------------------------------------------------
# Whole-rig forward kinematics (plain Python), for the gestures and their tests
# ---------------------------------------------------------------------------
def rest_rotation(head, tail):
    """Bone rest orientation with roll 0, as Blender builds it (vec_roll_to_mat3): the
    shortest-arc rotation taking +Y onto the bone direction. Columns are the bone's X, Y, Z
    axes in armature space. Valid away from bones pointing along -Y (none on this rig)."""
    d = [tail[i] - head[i] for i in range(3)]
    n = math.sqrt(sum(c * c for c in d))
    x, y, z = (c / n for c in d)
    t = 1.0 + y
    return [[1 - x * x / t, x, -x * z / t],
            [-x, y, -z],
            [-x * z / t, z, 1 - z * z / t]]


def _rest4(bone):
    _, head, tail, _ = BONES[bone]
    return _m4(rest_rotation(head, tail), head)


def pose_matrices(rot: dict, hips_loc=(0.0, 0.0, 0.0)) -> dict:
    """Armature-space pose matrix of every bone for local XYZ Euler rotations in degrees
    (bones missing from `rot` stay at rest) and the hips location, by Blender's evaluation
    pose(bone) = pose(parent) @ inv(rest(parent)) @ rest(bone) @ T(location) @ R(euler)."""
    out = {}
    for name, (parent, *_) in BONES.items():                  # parents come first
        local = _m4(_euler_xyz(*rot.get(name, (0.0, 0.0, 0.0))),
                    hips_loc if name == "hips" else (0.0, 0.0, 0.0))
        m = _mul(_rest4(name), local)
        if parent is not None:
            m = _mul(_mul(out[parent], _inv_rigid(_rest4(parent))), m)
        out[name] = m
    return out


def bone_points(mats: dict) -> dict:
    """{bone: (head, tail)} in armature space from pose_matrices()."""
    out = {}
    for name, m in mats.items():
        length = math.dist(BONES[name][1], BONES[name][2])
        out[name] = ([m[i][3] for i in range(3)], [m[i][1] * length + m[i][3] for i in range(3)])
    return out


def _euler_from_matrix(m) -> tuple[float, float, float]:
    """XYZ Euler (degrees) of a rotation matrix m = Rz @ Ry @ Rx."""
    y = math.asin(max(-1.0, min(1.0, -m[2][0])))
    return (math.degrees(math.atan2(m[2][1], m[2][2])), math.degrees(y),
            math.degrees(math.atan2(m[1][0], m[0][0])))


def _smootherstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * t * (t * (6 * t - 15) + 10)


# ---------------------------------------------------------------------------
# Gestures (Milestone 7): partial-body actions layered over a continuous idle
# ---------------------------------------------------------------------------
# A gesture keys only the channels it moves (bone -> {Euler axis: degrees}). On a higher NLA
# track (REPLACE) it overrides just those channels, and the idle on the track below keeps
# driving everything else: the legs and hips, so the feet stay planted, and for the look the
# breathing pitch (rotation_euler[0]) of the bones it turns. Gestures do not loop; after the
# clip, NLA holds the last key (HOLD_FORWARD in build_scene.place_actions).
LOOK = {"name": "mannequin_look", "frames": 24}
WAVE = {"name": "mannequin_wave", "frames": 60}
GESTURE_FRAMES = {LOOK["name"]: LOOK["frames"], WAVE["name"]: WAVE["frames"]}

# Look: the head and chest turn to the character's right and hold. The spine bones point up
# (+Z), so their local Y is world up and a negative Y rotation turns clockwise seen from above:
# the rig faces -Y, so that is toward -X, its right. Yaw per bone relative to its parent, and
# the frames over which each eases in (smootherstep): the head leads, the spine follows.
LOOK_YAW_DEG = {"spine": -6.0, "chest": -10.0, "neck": -9.0, "head": -15.0}   # head world -40
LOOK_WINDOW = {"head": (1, 11), "neck": (2, 13), "chest": (3, 15), "spine": (4, 17)}

# Wave (right arm): raise the upper arm out to the side and forward, bend the elbow so the
# forearm points up, swing the forearm side to side (elbow flexion about one horizontal axis,
# in the vertical plane of the raised arm), then lower back to the idle's mean arm pose. The
# raise and the lowering mirror each other: the upper arm turns along the shortest rotation
# between the two poses, and the elbow flexes only in the second part of the raise (and
# straightens first when lowering), so the hand stays in front of the body.
WAVE_SIDE = "R"
WAVE_ELEVATION_DEG = 25.0      # upper arm above horizontal
WAVE_FORWARD_DEG = 30.0        # upper arm swung forward (-Y) from straight out to the side
WAVE_FLEX_DEG = 60.0           # elbow flexion at the centre of the swing
WAVE_SWING_DEG = 22.0          # forearm swing amplitude, +- about WAVE_FLEX_DEG
WAVE_HAND_FACTOR = -0.4        # the hand counter-rotates against the swing (a loose wrist)
WAVE_CYCLES = 2
WAVE_RAMP = 3                  # frames over which the swing amplitude fades in and out
# gesture key frames (inclusive): upper arm raise, elbow flex, swing, elbow straighten, lower
WAVE_RAISE, WAVE_FLEX = (1, 19), (7, 19)
WAVE_SWING = (19, 43)
WAVE_UNFLEX, WAVE_LOWER = (43, 55), (43, 61)


def _wave_upper_arm_raised() -> tuple[float, float, float]:
    """Local Euler of the raised upper arm (chest at rest): its Y axis along the raised
    direction and its X axis (the forearm's flexion axis) horizontal and perpendicular to it,
    so elbow flexion swings the forearm up toward vertical in the arm's vertical plane."""
    sx = 1.0 if WAVE_SIDE == "L" else -1.0
    e, f = math.radians(WAVE_ELEVATION_DEG), math.radians(WAVE_FORWARD_DEG)
    u = [sx * math.cos(e) * math.cos(f), -math.cos(e) * math.sin(f), math.sin(e)]
    x = [u[1], -u[0], 0.0]                                      # u x (0, 0, 1)
    n = math.hypot(x[0], x[1])
    x = [c / n for c in x]
    z = [x[1] * u[2] - x[2] * u[1], x[2] * u[0] - x[0] * u[2], x[0] * u[1] - x[1] * u[0]]
    target = _cols(x, u, z)
    _, head, tail, _ = BONES[f"upper_arm.{WAVE_SIDE}"]
    r0 = rest_rotation(head, tail)
    local = [[sum(r0[k][i] * target[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return _euler_from_matrix(local)


WAVE_UPPER_ARM_DEG = _wave_upper_arm_raised()
# the idle's arm pose averaged over its cycle: upper arm 1.0 cos(.) about X averages to 0
IDLE_ARM_MEAN = {"upper_arm": (0.0, 0.0, 0.0), "forearm": (FORWARD * ELBOW_DEG, 0.0, 0.0),
                 "hand": (0.0, 0.0, 0.0)}


def _axis_angle(m) -> tuple[list[float], float]:
    """Unit axis and angle (rad) of a rotation matrix whose angle is below 180 degrees."""
    angle = math.acos(max(-1.0, min(1.0, (m[0][0] + m[1][1] + m[2][2] - 1) / 2)))
    if angle < 1e-12:
        return [1.0, 0.0, 0.0], 0.0
    v = [m[2][1] - m[1][2], m[0][2] - m[2][0], m[1][0] - m[0][1]]
    n = math.sqrt(sum(c * c for c in v))
    return [c / n for c in v], angle


def _rotation(axis, angle):
    x, y, z = axis
    c, s, k = math.cos(angle), math.sin(angle), 1 - math.cos(angle)
    return [[c + x * x * k, x * y * k - z * s, x * z * k + y * s],
            [y * x * k + z * s, c + y * y * k, y * z * k - x * s],
            [z * x * k - y * s, z * y * k + x * s, c + z * z * k]]


_WAVE_AXIS, _WAVE_ANGLE = _axis_angle(_euler_xyz(*WAVE_UPPER_ARM_DEG))


def wave_upper_arm(t: float) -> tuple[float, float, float]:
    """Upper-arm local Euler a fraction t of the way from the idle's mean arm (rest) to the
    raised arm, along the shortest rotation between them (a quaternion slerp). The Euler values
    themselves are not blended: the raised pose is near the XYZ gimbal (Y about -77 deg), and
    a straight Euler blend swings the hand out behind the body."""
    return _euler_from_matrix(_rotation(_WAVE_AXIS, t * _WAVE_ANGLE))


def _window(f: float, w: tuple[int, int]) -> float:
    return _smootherstep((f - w[0]) / (w[1] - w[0]))


def look_keys() -> list[tuple[int, dict]]:
    out = []
    for f in range(1, LOOK["frames"] + 2):
        rot = {}
        for bone, yaw in LOOK_YAW_DEG.items():
            a, b = LOOK_WINDOW[bone]
            rot[bone] = {1: _r(yaw * _smootherstep((f - a) / (b - a)))}
        out.append((f, rot))
    return out


def wave_arm(f: float) -> dict:
    """Local Euler (degrees) of the waving arm's three bones at gesture frame f."""
    s = WAVE_SIDE
    if WAVE_SWING[0] < f < WAVE_SWING[1]:
        u = f - WAVE_SWING[0]
        n = WAVE_SWING[1] - WAVE_SWING[0]
        env = _smootherstep(u / WAVE_RAMP) * _smootherstep((n - u) / WAVE_RAMP)
        swing = WAVE_SWING_DEG * env * math.sin(2 * math.pi * WAVE_CYCLES * u / n)
        return {f"upper_arm.{s}": list(WAVE_UPPER_ARM_DEG),
                f"forearm.{s}": [WAVE_FLEX_DEG + swing, 0.0, 0.0],
                f"hand.{s}": [WAVE_HAND_FACTOR * swing, 0.0, 0.0]}
    if f <= WAVE_SWING[0]:
        t, ft = _window(f, WAVE_RAISE), _window(f, WAVE_FLEX)
    else:
        t, ft = 1.0 - _window(f, WAVE_LOWER), 1.0 - _window(f, WAVE_UNFLEX)
    flex = IDLE_ARM_MEAN["forearm"][0] + ft * (WAVE_FLEX_DEG - IDLE_ARM_MEAN["forearm"][0])
    return {f"upper_arm.{s}": list(wave_upper_arm(t)),
            f"forearm.{s}": [flex, 0.0, 0.0], f"hand.{s}": list(IDLE_ARM_MEAN["hand"])}


def wave_keys() -> list[tuple[int, dict]]:
    return [(f, {bone: {i: _r(v) for i, v in enumerate(rot)} for bone, rot in wave_arm(f).items()})
            for f in range(1, WAVE["frames"] + 2)]


def gestures() -> dict[str, list[tuple[int, dict]]]:
    return {LOOK["name"]: look_keys(), WAVE["name"]: wave_keys()}


# ---------------------------------------------------------------------------
# Blender authoring (imports bpy lazily so the tables above stay testable without Blender)
# ---------------------------------------------------------------------------
def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="mannequin.py")
    p.add_argument("--out-root", required=True, type=Path,
                   help="directory to write characters/, actions/ and props/ into")
    p.add_argument("--force", action="store_true", help="overwrite existing output files")
    p.add_argument("--set", choices=("m6", "m7", "m11"), default="m6",
                   help="m6: character, walk/idle actions, baton (default); "
                        "m7: ochre character variant and gesture actions; "
                        "m11: both characters with head marker A")
    return p.parse_args(argv)


def _material(bpy, key: str):
    name, rgb = MATERIALS[key]
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*rgb, 1.0)
    if mat.node_tree is None:
        mat.use_nodes = True
    bsdf = next((n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"),
                None)
    if bsdf is None:
        raise RuntimeError(f"{name}: no Principled BSDF node")
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    bsdf.inputs["Roughness"].default_value = MATERIAL_ROUGHNESS.get(key, ROUGHNESS)
    return mat


def _part_matrix(shape: str, dims, head, tail):
    from mathutils import Matrix, Vector
    h, t = Vector(head), Vector(tail)
    mid = (h + t) / 2
    if shape == "box":
        return Matrix.Translation(mid) @ Matrix.Diagonal((*dims, 1.0))
    if shape == "ball":
        return Matrix.Translation(mid)
    d = t - h                                                  # cyl: local Z along the bone
    rot = Vector((0, 0, 1)).rotation_difference(d.normalized()).to_matrix().to_4x4()
    return Matrix.Translation(mid) @ rot


def _build_character(bpy, coll, armature=ARMATURE, body_name=BODY, materials=("body", "accent"),
                     marker: bool = False):
    import bmesh

    arm_data = bpy.data.armatures.new(armature)
    rig = bpy.data.objects.new(armature, arm_data)
    coll.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    for name, (_, head, tail, _) in BONES.items():
        eb = arm_data.edit_bones.new(name)
        eb.head, eb.tail, eb.roll = head, tail, 0.0
    for name, (parent, _, _, connected) in BONES.items():
        if parent:
            eb = arm_data.edit_bones[name]
            eb.parent = arm_data.edit_bones[parent]
            eb.use_connect = connected
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in rig.pose.bones:
        pb.rotation_mode = "XYZ"

    mesh = bpy.data.meshes.new(body_name)
    body = bpy.data.objects.new(body_name, mesh)
    coll.objects.link(body)
    body.parent = rig
    groups = {name: body.vertex_groups.new(name=name).index for name in BONES}
    mod = body.modifiers.new("Armature", "ARMATURE")
    mod.object = rig
    mats = [_material(bpy, key) for key in materials]
    for m in mats:
        mesh.materials.append(m)

    bm = bmesh.new()
    deform = bm.verts.layers.deform.verify()
    for bone, (shape, dims, mat_key) in PARTS.items():
        _, head, tail, _ = BONES[bone]
        length = math.dist(head, tail)
        if shape == "box":
            verts = bmesh.ops.create_cube(bm, size=1.0)["verts"]
        elif shape == "ball":
            verts = bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=8,
                                              radius=dims[0])["verts"]
        else:
            verts = bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=8,
                                          radius1=dims[0], radius2=dims[0],
                                          depth=length)["verts"]
        bmesh.ops.transform(bm, matrix=_part_matrix(shape, dims, head, tail), verts=verts)
        index = 0 if mat_key == "body" else 1
        for v in verts:
            v[deform][groups[bone]] = 1.0
            for f in v.link_faces:
                f.material_index = index
    if marker:                                  # head marker A: two boxes on the head bone
        from mathutils import Matrix
        for centre, dims, role in MARKER_A.values():
            verts = bmesh.ops.create_cube(bm, size=1.0)["verts"]
            bmesh.ops.transform(bm, matrix=Matrix.Translation(centre) @ Matrix.Diagonal((*dims, 1.0)),
                                verts=verts)
            for v in verts:
                v[deform][groups[MARKER_BONE]] = 1.0
                for f in v.link_faces:
                    f.material_index = MATERIAL_SLOT[role]
    bm.to_mesh(mesh)
    bm.free()
    return rig


def _author_actions(bpy, rig) -> list:
    ad = rig.animation_data_create()
    out = []
    for name, keys in actions().items():
        act = bpy.data.actions.new(name)
        ad.action = act
        for frame, pose in keys:
            for bone, rot in pose["rot"].items():
                pb = rig.pose.bones[bone]
                pb.rotation_euler = [math.radians(v) for v in rot]
                pb.keyframe_insert("rotation_euler", frame=frame, group=bone)
            hips = rig.pose.bones["hips"]
            hips.location = pose["hips_loc"]
            hips.keyframe_insert("location", frame=frame, group="hips")
        act.use_frame_range = True
        act.frame_start, act.frame_end = keys[0][0], keys[-1][0]
        out.append(act)
    rig.animation_data_clear()
    for pb in rig.pose.bones:                                  # save the rest pose
        pb.location = (0, 0, 0)
        pb.rotation_euler = (0, 0, 0)
    return out


def _author_gestures(bpy, rig) -> list:
    """Key only the channels each gesture moves (one F-curve per bone and Euler axis), so the
    action layers over an idle on a lower NLA track."""
    ad = rig.animation_data_create()
    out = []
    for name, keys in gestures().items():
        act = bpy.data.actions.new(name)
        ad.action = act
        for frame, rot in keys:
            for bone, axes in rot.items():
                pb = rig.pose.bones[bone]
                for axis, deg in axes.items():
                    pb.rotation_euler[axis] = math.radians(deg)
                    pb.keyframe_insert("rotation_euler", index=axis, frame=frame, group=bone)
        act.use_frame_range = True
        act.frame_start, act.frame_end = keys[0][0], keys[-1][0]
        out.append(act)
    rig.animation_data_clear()
    return out


def _build_prop(bpy, coll):
    import bmesh
    from mathutils import Matrix

    mesh = bpy.data.meshes.new(PROP_OBJECT)
    obj = bpy.data.objects.new(PROP_OBJECT, mesh)
    coll.objects.link(obj)
    mesh.materials.append(_material(bpy, "baton"))
    bm = bmesh.new()
    # 0.9 m along local Z with the origin (grip) 0.3 m from the lower end
    verts = bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=8,
                                  radius1=0.015, radius2=0.015, depth=0.9)["verts"]
    bmesh.ops.transform(bm, matrix=Matrix.Translation((0, 0, 0.15)), verts=verts)
    bm.to_mesh(mesh)
    bm.free()


def _write(bpy, root: Path, rel: Path, datablocks: set) -> tuple[Path, Path]:
    final = root / rel
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_name(final.stem + ".tmp.blend")
    bpy.data.libraries.write(str(tmp), datablocks, fake_user=True)
    return tmp, final


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    root = args.out_root.resolve()
    outputs = {"m6": OUTPUTS, "m7": M7_OUTPUTS, "m11": M11_OUTPUTS}[args.set]
    existing = [str(root / rel) for rel in outputs if (root / rel).exists()]
    if existing and not args.force:
        print(f"[mannequin] REFUSED: output exists (pass --force to overwrite): {existing}",
              file=sys.stderr)
        return 2

    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    if args.set == "m7":
        return _main_m7(bpy, root)
    if args.set == "m11":
        return _main_m11(bpy, root)
    scene = bpy.context.scene
    char_coll = bpy.data.collections.new(CHARACTER_COLLECTION)
    prop_coll = bpy.data.collections.new(PROP_COLLECTION)
    scene.collection.children.link(char_coll)
    scene.collection.children.link(prop_coll)

    rig = _build_character(bpy, char_coll)
    acts = _author_actions(bpy, rig)
    _build_prop(bpy, prop_coll)

    written = []
    try:
        written.append(_write(bpy, root, CHARACTER_FILE, {char_coll}))
        written.append(_write(bpy, root, ACTIONS_FILE, set(acts)))
        written.append(_write(bpy, root, PROP_FILE, {prop_coll}))
        for tmp, final in written:
            os.replace(tmp, final)
    finally:
        for tmp, _ in written:
            if tmp.exists():
                tmp.unlink()
    _report(written)
    return 0


def _report(written: list) -> None:
    for _, final in written:
        print(f"[mannequin] wrote {final}")


def _main_m7(bpy, root: Path) -> int:
    """The ochre variant and the gestures. The gestures are keyed on a rig named ARMATURE (not
    written), so their slot is OBRIG-mannequin, the same as the walk and idle."""
    scene = bpy.context.scene
    ochre_coll = bpy.data.collections.new(OCHRE["collection"])
    work_coll = bpy.data.collections.new("WORK-gesture_rig")
    scene.collection.children.link(ochre_coll)
    scene.collection.children.link(work_coll)
    _build_character(bpy, ochre_coll, OCHRE["armature"], OCHRE["body"], OCHRE["materials"])
    acts = _author_gestures(bpy, _build_character(bpy, work_coll))
    written = []
    try:
        written.append(_write(bpy, root, OCHRE_FILE, {ochre_coll}))
        written.append(_write(bpy, root, GESTURES_FILE, set(acts)))
        for tmp, final in written:
            os.replace(tmp, final)
    finally:
        for tmp, _ in written:
            if tmp.exists():
                tmp.unlink()
    _report(written)
    return 0


def _main_m11(bpy, root: Path) -> int:
    """Both characters with head marker A, each in its own file under its own names."""
    scene = bpy.context.scene
    written = []
    try:
        for spec, rel in ((MARKED, MARKED_FILE), (OCHRE_MARKED, OCHRE_MARKED_FILE)):
            coll = bpy.data.collections.new(spec["collection"])
            scene.collection.children.link(coll)
            _build_character(bpy, coll, spec["armature"], spec["body"], spec["materials"], marker=True)
            written.append(_write(bpy, root, rel, {coll}))
        for tmp, final in written:
            os.replace(tmp, final)
    finally:
        for tmp, _ in written:
            if tmp.exists():
                tmp.unlink()
    _report(written)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []))
