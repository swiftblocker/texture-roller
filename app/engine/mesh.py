"""Structured-grid mesh: outer surface from the radius map, welded at theta 0/2pi, bore, caps, split keys.

Watertight and radially monotone by construction (R41, R65, R66, R69). No boolean engine is used: the
split tongue/groove is built directly into the cap triangulation of the joint face.
"""
from __future__ import annotations
import math
import numpy as np
import trimesh

BORE_CHAMFER = 0.5
KEY_W = 2.0
KEY_H = 2.0
KEY_CLEAR = 0.15


class _B:
    def __init__(self):
        self.v, self.f, self.n = [], [], 0

    def add(self, v):
        v = np.asarray(v, float)
        idx = np.arange(self.n, self.n + len(v))
        self.v.append(v)
        self.n += len(v)
        return idx


def _ring(cs, sn, r, z):
    r = np.broadcast_to(np.asarray(r, float), cs.shape)
    return np.stack([r * cs, r * sn, np.full(cs.shape, float(z))], 1)


def _strip(b, A, Bq, flip, cols=None):
    N = len(A)
    j = np.arange(N) if cols is None else np.asarray(cols)
    j1 = (j + 1) % N
    a0, a1, b0, b1 = A[j], A[j1], Bq[j], Bq[j1]
    t1 = np.stack([a0, a1, b1], 1)
    t2 = np.stack([a0, b1, b0], 1)
    t = np.concatenate([t1, t2])
    if flip:
        t = t[:, ::-1]
    b.f.append(t)


def _quads_oriented(b, P4, I4, expect):
    """quad points P4 (4,K,3), indices I4 (4,K); flip each so its normal agrees with expect (K,3)."""
    n = np.cross(P4[1] - P4[0], P4[2] - P4[0]) + np.cross(P4[2] - P4[0], P4[3] - P4[0])
    flip = (n * expect).sum(1) < 0
    t1 = np.stack([I4[0], I4[1], I4[2]], 1)
    t2 = np.stack([I4[0], I4[2], I4[3]], 1)
    t1f = np.stack([I4[0], I4[2], I4[1]], 1)
    t2f = np.stack([I4[0], I4[3], I4[2]], 1)
    b.f.append(np.where(flip[:, None], t1f, t1))
    b.f.append(np.where(flip[:, None], t2f, t2))


def key_spec(kind, r_outer_min, bore_r, pt):
    """-> dict or None. Tongue (A top) and groove (B bottom), tangentially centred on theta = 0."""
    r0 = bore_r + 1.0 if bore_r > 0 else 2.0
    r1 = r_outer_min - 1.0
    if r1 - r0 < 2.0:
        return None
    kc = max(2, int(round(KEY_W / pt)))
    if kind == "tongue":
        cols = np.arange(-(kc // 2), kc - kc // 2 + 0) % 10 ** 9
        h = KEY_H
        rr = (r0, r1)
        ncols = kc
    else:
        ncols = kc + 2
        h = KEY_H + 0.3
        rr = (r0 - 0.2 if bore_r > 0 else r0, r1 + 0.2)
    return {"kind": kind, "r0": rr[0], "r1": rr[1], "ncols": ncols, "h": h}


def _cap(b, cs, sn, N, z, nsign, outer_idx, inner_idx, center, key):
    """nsign=+1 for a top cap (normal +z), -1 bottom. key lifted away (tongue) or into (groove) the body."""
    flip = nsign < 0
    chain = [outer_idx]
    if key is not None:
        r0, r1 = key["r0"], key["r1"]
        ring1 = b.add(_ring(cs, sn, r1, z))
        ring0 = b.add(_ring(cs, sn, r0, z))
        chain += [ring1, ring0]
    if inner_idx is not None:
        chain.append(inner_idx)
    for k in range(len(chain) - 1):
        cols = None
        if key is not None and k == 1:  # ring1 -> ring0 strip skips the key columns
            m = np.ones(N, bool)
            m[key["J"]] = False
            cols = np.nonzero(m)[0]
        _strip(b, chain[k], chain[k + 1], flip, cols)
    if inner_idx is None:  # fan to centre (no bore)
        last = chain[-1]
        j = np.arange(N)
        t = np.stack([last[j], last[(j + 1) % N], np.full(N, center)], 1)
        b.f.append(t[:, ::-1] if flip else t)
    if key is not None:
        J = key["J"]
        Jv = np.concatenate([J, [(J[-1] + 1) % N]])
        dz = key["h"] * nsign * (1 if key["kind"] == "tongue" else -1)
        L1 = b.add(_ring(cs[Jv], sn[Jv], key["r1"], z + dz))
        L0 = b.add(_ring(cs[Jv], sn[Jv], key["r0"], z + dz))
        # lifted face (same orientation as the cap)
        t1 = np.stack([L1[:-1], L1[1:], L0[1:]], 1)
        t2 = np.stack([L1[:-1], L0[1:], L0[:-1]], 1)
        t = np.concatenate([t1, t2])
        b.f.append(t[:, ::-1] if flip else t)
        s = 1.0 if key["kind"] == "tongue" else -1.0
        V = lambda idx: np.concatenate(b.v)[idx]  # noqa: E731 (small gather)
        vall = np.concatenate(b.v)
        base1, base0 = chain[1], chain[2]
        th = 2 * math.pi * Jv / N
        rad = np.stack([np.cos(th), np.sin(th), np.zeros_like(th)], 1)
        tan = np.stack([-np.sin(th), np.cos(th), np.zeros_like(th)], 1)
        # r1 wall and r0 wall, columns pairs
        for (base, lift, sgn) in ((base1, L1, s), (base0, L0, -s)):
            I4 = np.stack([base[Jv[:-1]], base[Jv[1:]], lift[1:], lift[:-1]])
            P4 = vall[I4]
            ex = sgn * (rad[:-1] + rad[1:])
            _quads_oriented(b, P4, I4, ex)
        for (jj, sgn) in ((0, -s), (len(Jv) - 1, s)):  # end walls
            I4 = np.stack([[base0[Jv[jj]]], [base1[Jv[jj]]], [L1[jj]], [L0[jj]]])
            P4 = vall[I4]
            _quads_oriented(b, P4, I4, sgn * tan[jj:jj + 1])


def build_part(R, z, bore_r, bottom_true=True, top_true=True, bottom_key=None, top_key=None):
    """R: (rows,N) outer radii; z: (rows,). Returns trimesh.Trimesh."""
    rows, N = R.shape
    th = 2 * math.pi * np.arange(N) / N
    cs, sn = np.cos(th), np.sin(th)
    b = _B()
    outer = np.stack([R * cs, R * sn, np.broadcast_to(z[:, None], R.shape)], 2).reshape(-1, 3)
    b.add(outer)
    idx = np.arange(rows * N).reshape(rows, N)
    ia, ib = idx[:-1], idx[1:]
    ia1, ib1 = np.roll(ia, -1, 1), np.roll(ib, -1, 1)
    b.f.append(np.concatenate([np.stack([ia, ia1, ib1], 2).reshape(-1, 3), np.stack([ia, ib1, ib], 2).reshape(-1, 3)]))
    # bore rings bottom -> top
    brings = []
    z0, z1 = float(z[0]), float(z[-1])
    if bore_r > 0:
        if bottom_true:
            brings.append(b.add(_ring(cs, sn, bore_r + BORE_CHAMFER, z0)))
            brings.append(b.add(_ring(cs, sn, bore_r, z0 + BORE_CHAMFER)))
        else:
            brings.append(b.add(_ring(cs, sn, bore_r, z0)))
        if top_true:
            brings.append(b.add(_ring(cs, sn, bore_r, z1 - BORE_CHAMFER)))
            brings.append(b.add(_ring(cs, sn, bore_r + BORE_CHAMFER, z1)))
        else:
            brings.append(b.add(_ring(cs, sn, bore_r, z1)))
        for k in range(len(brings) - 1):
            _strip(b, brings[k], brings[k + 1], True)
    cb = ct = None
    if bore_r <= 0:
        cb = int(b.add(np.array([[0, 0, z0]]))[0])
        ct = int(b.add(np.array([[0, 0, z1]]))[0])
    for kk in (bottom_key, top_key):
        if kk is not None:
            J = np.arange(-(kk["ncols"] // 2), kk["ncols"] - kk["ncols"] // 2) % N
            kk["J"] = J
    _cap(b, cs, sn, N, z0, -1, idx[0], brings[0] if brings else None, cb, bottom_key)
    _cap(b, cs, sn, N, z1, +1, idx[-1], brings[-1] if brings else None, ct, top_key)
    V = np.concatenate(b.v)
    F = np.concatenate(b.f).astype(np.int64)
    m = trimesh.Trimesh(vertices=V, faces=F, process=False)
    m.metadata["n_outer"] = rows * N
    m.metadata["bore_r"] = bore_r
    return m


def build_parts(P, R, lay):
    """-> list of (name, mesh, expected (dia, length)). R full radius map (M,N)."""
    M, N = R.shape
    z = np.arange(M) * lay.pz
    bore = P.bore_used
    D = P.diameter
    if not P.split:
        return [("roller", build_part(R, z, bore), (D, P.length))]
    mid = (M - 1) // 2
    rj = float(R[mid].min())
    kt = key_spec("tongue", rj, bore, lay.pt)
    kg = key_spec("groove", rj, bore, lay.pt)
    if kt is None or kg is None:
        kt = kg = None
    A = build_part(R[:mid + 1], z[:mid + 1], bore, bottom_true=True, top_true=False, top_key=kt)
    B = build_part(R[mid:], z[mid:], bore, bottom_true=False, top_true=True, bottom_key=kg)
    A.metadata["key"] = B.metadata["key"] = kt is not None
    la = z[mid] + (KEY_H if kt else 0.0)
    return [("roller_a", A, (D, la)), ("roller_b", B, (D, P.length - z[mid]))]


# ------------------------------------------------------------ validation
def edge_checks(F, nv):
    """-> (watertight, winding_consistent). Directed edge keys; each must occur once, with its reverse once."""
    a = np.concatenate([F[:, 0], F[:, 1], F[:, 2]]).astype(np.int64)
    b = np.concatenate([F[:, 1], F[:, 2], F[:, 0]]).astype(np.int64)
    fw = np.sort(a * nv + b)
    rv = np.sort(b * nv + a)
    dup = bool(np.any(fw[1:] == fw[:-1]))
    closed = bool(np.array_equal(fw, rv))
    return (closed and not dup), (not dup)


def radial_ray_check(mesh, n_rays=40, seed=1, bore=True):
    """Cast rays from the axis at random (theta,z); count crossings. Expected 2 (bore + outer) or 1."""
    V, F = mesh.vertices, mesh.faces
    z0, z1 = V[:, 2].min(), V[:, 2].max()
    tri = V[F]
    zmin, zmax = tri[:, :, 2].min(1), tri[:, :, 2].max(1)
    rng = np.random.default_rng(seed)
    bad = 0
    want = 2 if mesh.metadata.get("bore_r", 0) > 0 else 1
    for _ in range(n_rays):
        z = rng.uniform(z0 + 3.0, z1 - 3.0)
        th = rng.uniform(0, 2 * math.pi)
        sel = np.nonzero((zmin <= z + 1e-6) & (zmax >= z - 1e-6))[0]
        T = tri[sel]
        d = np.array([math.cos(th), math.sin(th), 0.0])
        o = np.array([0.0, 0.0, z])
        e1, e2 = T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]
        h = np.cross(d, e2)
        det = (e1 * h).sum(1)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1.0 / np.where(ok, det, 1), 0)
        s = o - T[:, 0]
        u = (s * h).sum(1) * inv
        q = np.cross(s, e1)
        v = (d * q).sum(1) * inv
        t = (e2 * q).sum(1) * inv
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-9)
        if int(hit.sum()) != want:
            bad += 1
    return bad


def validate(mesh, expected, n_rays=40):
    """-> dict of measurements used by R65-R70."""
    V, F = mesh.vertices, mesh.faces
    w, c = edge_checks(F, len(V))
    vol = float(mesh.volume)
    bb = mesh.bounds
    dia_x = bb[1][0] - bb[0][0]
    dia_y = bb[1][1] - bb[0][1]
    length = bb[1][2] - bb[0][2]
    dia = max(dia_x, dia_y)
    err = max(abs(dia - expected[0]), abs(length - expected[1]))
    n_out = mesh.metadata["n_outer"]
    r = np.hypot(V[:n_out, 0], V[:n_out, 1])
    br = mesh.metadata.get("bore_r", 0.0)
    return {
        "watertight": w, "winding_consistent": c, "volume": vol,
        "bbox": [float(dia_x), float(dia_y), float(length)], "bbox_error": float(err),
        "bad_rays": radial_ray_check(mesh, n_rays),
        "mesh_t_min": float(r.min() - br),
        "triangles": int(len(F)), "vertices": int(len(V)),
    }
