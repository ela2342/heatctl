"""A small dense Kalman filter, in pure Python.

No numpy. That is a deliberate cost: the runtime dependency set is part of
this project's 30-year-maintainability promise (see CLAUDE.md), and the
filters this layer needs are 2x2 and 3x3. At that size an explicit
implementation is both faster than the array machinery and far easier to
read in ten years than a call into a library whose API has moved on.

Matrices are lists of rows; vectors are flat lists. Everything is
immutable-by-convention: operations return new objects rather than writing
through, because aliasing bugs in a filter show up as slow divergence rather
than an exception.
"""
from __future__ import annotations

Matrix = list[list[float]]
Vector = list[float]


# ---------- small dense linear algebra ----------

def eye(n: int) -> Matrix:
    return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]


def matmul(a: Matrix, b: Matrix) -> Matrix:
    cols = range(len(b[0]))
    return [[sum(a[i][k] * b[k][j] for k in range(len(b))) for j in cols]
            for i in range(len(a))]


def matvec(a: Matrix, v: Vector) -> Vector:
    return [sum(a[i][k] * v[k] for k in range(len(v))) for i in range(len(a))]


def transpose(a: Matrix) -> Matrix:
    return [list(col) for col in zip(*a)]


def madd(a: Matrix, b: Matrix) -> Matrix:
    return [[x + y for x, y in zip(ra, rb)] for ra, rb in zip(a, b)]


def msub(a: Matrix, b: Matrix) -> Matrix:
    return [[x - y for x, y in zip(ra, rb)] for ra, rb in zip(a, b)]


def scale(a: Matrix, s: float) -> Matrix:
    return [[x * s for x in row] for row in a]


def inverse(a: Matrix) -> Matrix:
    """Gauss-Jordan with partial pivoting.

    Raises ValueError on a singular matrix rather than returning something
    plausible-looking. A silently wrong inverse here would corrupt the state
    covariance and the filter would drift for hours before anyone noticed.
    """
    n = len(a)
    aug = [list(a[i]) + eye(n)[i] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[piv][col]) < 1e-12:
            raise ValueError("singular matrix")
        aug[col], aug[piv] = aug[piv], aug[col]
        d = aug[col][col]
        aug[col] = [x / d for x in aug[col]]
        for r in range(n):
            if r == col:
                continue
            f = aug[r][col]
            if f:
                aug[r] = [x - f * y for x, y in zip(aug[r], aug[col])]
    return [row[n:] for row in aug]


def expm(a: Matrix, terms: int = 18) -> Matrix:
    """Matrix exponential, by scaling-and-squaring around a Taylor series.

    Used to discretise the continuous-time thermal model exactly rather than
    with a forward-Euler step. Euler would in fact be adequate here - the
    building's fastest time constant is around an hour against a 60 s step -
    but "adequate at the sample rate we happen to use today" is a property
    that quietly stops holding when someone changes the sample rate, and the
    failure is a biased slab estimate rather than anything that looks like a
    bug.

    The scaling step is not decoration either. A bare truncated series is
    accurate only while `A` is small, which it is for the thermal model at a
    60 s step - but that made correctness a function of the caller's step
    size, and a 20-minute step is a perfectly reasonable thing for a planner
    to ask for. Halving `A` until its norm is under 1/2 and squaring the
    result back up makes the accuracy independent of the argument.
    """
    n = len(a)
    norm = max((sum(abs(x) for x in row) for row in a), default=0.0)
    squarings = 0
    while norm > 0.5:
        a = scale(a, 0.5)
        norm *= 0.5
        squarings += 1
    result = eye(n)
    term = eye(n)
    for k in range(1, terms + 1):
        term = scale(matmul(term, a), 1.0 / k)
        result = madd(result, term)
    for _ in range(squarings):
        result = matmul(result, result)
    return result


# ---------- the filter ----------

class KalmanFilter:
    """Linear KF with a control input: x' = F x + G u, z = H x + v.

    `F` and `G` are the DISCRETE-time matrices for one step; build them with
    `discretise()` in model.py rather than by hand.

    The update step accepts a partial measurement vector so a room whose
    sensor has gone quiet can still be predicted forward - that is the whole
    point of running a filter rather than differencing readings. Call
    `predict()` every step and `update()` only when a measurement arrives.
    """

    def __init__(self, x: Vector, P: Matrix, Q: Matrix, R: Matrix,
                 H: Matrix) -> None:
        self.x = list(x)
        self.P = [list(r) for r in P]
        self.Q = [list(r) for r in Q]
        self.R = [list(r) for r in R]
        self.H = [list(r) for r in H]
        # Innovation record. WP-F's acceptance gate is stated in terms of
        # innovation whiteness and bias over weeks, so the filter has to keep
        # the raw material for that test rather than leaving it to be
        # reconstructed from logs afterwards.
        self.innovations: list[float] = []

    def predict(self, F: Matrix, G: Matrix, u: Vector) -> None:
        # Dimensions are checked rather than left to zip, which truncates to
        # the shorter operand. A G with the wrong number of rows would
        # silently SHORTEN the state vector and the filter would carry on
        # producing numbers - the same class of quiet corruption that
        # `inverse` refuses to commit above.
        n = len(self.x)
        if len(F) != n or any(len(r) != n for r in F):
            raise ValueError(f"F must be {n}x{n}, got {len(F)}x{len(F[0])}")
        if len(G) != n or any(len(r) != len(u) for r in G):
            raise ValueError(f"G must be {n}x{len(u)}")
        self.x = [a + b for a, b in zip(matvec(F, self.x), matvec(G, u))]
        self.P = madd(matmul(matmul(F, self.P), transpose(F)), self.Q)

    def update(self, z: Vector) -> Vector:
        """Fold in a measurement. Returns the innovation (z - Hx)."""
        Ht = transpose(self.H)
        y = [a - b for a, b in zip(z, matvec(self.H, self.x))]
        S = madd(matmul(matmul(self.H, self.P), Ht), self.R)
        K = matmul(matmul(self.P, Ht), inverse(S))
        self.x = [a + b for a, b in zip(self.x, matvec(K, y))]
        # Joseph form. The textbook `(I-KH)P` is algebraically identical but
        # loses symmetry and positive-definiteness to rounding over long runs,
        # and this filter is meant to run for months without a restart.
        n = len(self.x)
        A = msub(eye(n), matmul(K, self.H))
        self.P = madd(matmul(matmul(A, self.P), transpose(A)),
                      matmul(matmul(K, self.R), transpose(K)))
        self.innovations.extend(y)
        del self.innovations[:-5000]
        return y

    def innovation_stats(self) -> dict[str, float]:
        """Mean/sd/whiteness of recent innovations - the WP-F gate metrics.

        `lag1` is the lag-1 autocorrelation. A well-specified filter leaves
        white innovations, so a value far from zero says the model is missing
        a mode - which for this building most likely means solar gain or the
        stove, both of which are deliberately unmodelled disturbances today.
        """
        v = self.innovations
        n = len(v)
        if n < 3:
            return {"n": float(n), "mean": 0.0, "sd": 0.0, "lag1": 0.0}
        mean = sum(v) / n
        var = sum((x - mean) ** 2 for x in v) / n
        if var <= 0.0:
            return {"n": float(n), "mean": mean, "sd": 0.0, "lag1": 0.0}
        cov = sum((v[i] - mean) * (v[i - 1] - mean) for i in range(1, n)) / n
        return {"n": float(n), "mean": mean, "sd": var ** 0.5,
                "lag1": cov / var}
