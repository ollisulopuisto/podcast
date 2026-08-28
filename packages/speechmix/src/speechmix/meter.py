"""Äänekkyys virrasta, ITU-R BS.1770-4.

Koko ohjelmaa ei voi mitata kerralla: 77 minuuttia on 890 megatavua
float32:na, ja isäntä lukee stemit paloissa muutenkin. Äänekkyys on
lohkoittainen suure, joten se voidaan kerätä virrasta — kunhan suotimien
tila kannetaan palan rajan yli.

Se on tämän moduulin koko vaikeus. K-painotus on kaksi IIR-suodinta, ja
tilaton palakohtainen suodatus jättää jokaiseen rajaan transientin: lukema
on uskottava, vain väärä, ja väärässä suunnassa sitä enemmän mitä pienempi
pala. Testi vertaa lukemaa kerralla mitattuun kolmella eri palakoolla.

Portti on kaksivaiheinen kuten standardissa: absoluuttinen -70 LUFS ja
suhteellinen 10 LU jäljelle jääneiden keskiarvon alle. Ilman jälkimmäistä
puheen tauot painaisivat lukemaa alaspäin sitä enemmän mitä enemmän niitä
on — eli mitä rauhallisempi ohjelma, sitä kovemmaksi se mitattaisiin.
"""

import numpy as np

#: Lohko ja limitys standardin mukaan: 400 ms, 75 % päällekkäin.
BLOCK_SEC = 0.400
OVERLAP = 4

#: Portit, LUFS ja LU.
ABSOLUTE_GATE = -70.0
RELATIVE_GATE = 10.0


def _k_weighting(rate: int):
    """K-painotuksen kertoimet: korkeahylly ja ylipäästö, BS.1770-4."""
    from scipy import signal as _sig

    # Vaihe 1, «shelving»: pään ja vartalon aiheuttama korostus.
    f0, gain_db, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = np.tan(np.pi * f0 / rate)
    vh = 10 ** (gain_db / 20.0)
    vb = vh**0.4996667741545416
    a0 = 1.0 + k / q + k * k
    b = np.array([
        (vh + vb * k / q + k * k) / a0,
        2.0 * (k * k - vh) / a0,
        (vh - vb * k / q + k * k) / a0,
    ])
    a = np.array([1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / q + k * k) / a0])

    # Vaihe 2, «RLB»: matalien painon vähennys.
    f0, q = 38.13547087602444, 0.5003270373238773
    k = np.tan(np.pi * f0 / rate)
    b2 = np.array([1.0, -2.0, 1.0])
    a2 = np.array([
        1.0,
        2.0 * (k * k - 1.0) / (1.0 + k / q + k * k),
        (1.0 - k / q + k * k) / (1.0 + k / q + k * k),
    ])
    return (b, a), (b2, a2), _sig


class IntegratedMeter:
    """Kerää ohjelman äänekkyyden paloista. Mono sisään.

    ``add`` saa palan mitä tahansa pituutta; ``value`` antaa integroidun
    lukeman LUFS:eina tai ``None`` jos portin yli ei jäänyt mitään.
    """

    def __init__(self, rate: int):
        self.rate = int(rate)
        (self._b1, self._a1), (self._b2, self._a2), self._sig = _k_weighting(rate)
        self._z1 = np.zeros(2)
        self._z2 = np.zeros(2)
        self.step = max(1, int(round(BLOCK_SEC * rate / OVERLAP)))
        self._tail = np.zeros(0, dtype=np.float64)
        # Osalohkojen tehot: koko lohko on OVERLAP peräkkäistä osaa.
        self._powers: list[float] = []

    def add(self, block) -> None:
        """Lisää palan. Suotimen tila jatkuu palasta toiseen."""
        x = np.asarray(block, dtype=np.float64)
        if x.ndim > 1:
            x = x.mean(axis=0)
        if not x.size:
            return
        y, self._z1 = self._sig.lfilter(self._b1, self._a1, x, zi=self._z1)
        y, self._z2 = self._sig.lfilter(self._b2, self._a2, y, zi=self._z2)
        data = np.concatenate((self._tail, y)) if self._tail.size else y
        count = data.size // self.step
        if count:
            usable = data[: count * self.step].reshape(count, self.step)
            self._powers.extend(np.mean(usable**2, axis=1).tolist())
        self._tail = data[count * self.step :].copy()

    def _blocks(self) -> np.ndarray:
        """Lohkojen tehot: OVERLAP peräkkäistä osaa yhtä lohkoa kohden."""
        power = np.asarray(self._powers)
        if power.size < OVERLAP:
            return np.zeros(0)
        window = np.lib.stride_tricks.sliding_window_view(power, OVERLAP)
        return window.mean(axis=1)

    def value(self) -> float | None:
        """Integroitu äänekkyys, LUFS. ``None`` jos portin yli ei jää mitään."""
        blocks = self._blocks()
        if not blocks.size:
            return None
        with np.errstate(divide="ignore"):
            level = -0.691 + 10.0 * np.log10(blocks)
        keep = level > ABSOLUTE_GATE
        if not keep.any():
            return None
        # Suhteellinen portti lasketaan absoluuttisen läpäisseistä.
        reference = -0.691 + 10.0 * np.log10(blocks[keep].mean())
        keep &= level > reference - RELATIVE_GATE
        if not keep.any():
            return None
        return float(-0.691 + 10.0 * np.log10(blocks[keep].mean()))
