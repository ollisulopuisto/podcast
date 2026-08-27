"""Alueiden pilkkominen ja hiljaisten palojen vaimennus."""

from __future__ import annotations


from lxml import etree

from ..nhsx.read import localname, seconds_to_time, time_to_seconds


def merge(intervals: list[tuple[float, float]], max_gap: float = 0.0) -> list[tuple[float, float]]:
    """Yhdistää jaksot, joiden väli on korkeintaan ``max_gap``."""
    if not intervals:
        return []
    ordered = sorted(intervals)
    merged = [list(ordered[0])]
    for start, end in ordered[1:]:
        if start <= merged[-1][1] + max_gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


def audible_zones(
    intervals: list[tuple[float, float]], tail: float, gap: float
) -> list[tuple[float, float]]:
    """Puhejaksoista kuuluviksi jätettävät alueet.

    Kolme vaihetta, tässä järjestyksessä: sulje lyhyet tauot, lisää häntä
    molempiin päihin, yhdistä hännät jotka menivät päällekkäin.

    Kaksi säädintä sulkee taukoja, ja se on syytä tietää: tauko sulkeutuu jos
    se on lyhyempi kuin ``gap`` **tai** lyhyempi kuin kaksi kertaa ``tail``.
    Häntä puoli sekuntia sulkee sekunnin tauon vaikka «lyhin tauko» olisi
    0,4 — hännät kohtaavat keskellä. Järjestys on silti tämä eikä toisin
    päin: hännän lisääminen ensin sulkisi tauot pituuteen ``gap + 2 × tail``
    asti, eli kaksi säädintä laskisi yhteen sen sijaan että suurempi
    ratkaisee.
    """
    groups = merge(intervals, gap)
    padded = [(max(0.0, start - tail), end + tail) for start, end in groups]
    return merge(padded, 0.0)


def split_track(track_elem, zones: list[tuple[float, float]]) -> tuple[int, int]:
    """Pilkkoo raidan alueet ja vaimentaa palat jotka jäävät kuuluvien ulkopuolelle.

    Palauttaa (kuuluvat palat, vaimennetut palat).

    Alueen lapsielementtejä ei kopioida. Ne olisivat esimerkiksi häivytyksiä,
    joiden merkitys pilkotulle palalle ei ole sama kuin kokonaiselle alueelle:
    sama häivytys jokaisessa sadassa palassa on eri asia kuin yksi häivytys
    alueen alussa. Colab-muistikirja teki samoin; ero on siinä, että täällä
    siitä kerrotaan.
    """
    heard = muted = 0
    originals = [c for c in track_elem if localname(c) == "Region"]

    for region in originals:
        start = time_to_seconds(region.get("Start"))
        length = time_to_seconds(region.get("Length"))
        end = start + length
        offset = time_to_seconds(region.get("Offset", "0"))
        position = list(track_elem).index(region)

        edges = {start, end}
        for zone_start, zone_end in zones:
            if start < zone_start < end:
                edges.add(zone_start)
            if start < zone_end < end:
                edges.add(zone_end)
        cuts = sorted(edges)

        pieces = []
        for a, b in zip(cuts, cuts[1:]):
            middle = (a + b) / 2
            audible = any(z0 <= middle <= z1 for z0, z1 in zones)
            piece = etree.Element(region.tag, dict(region.attrib))
            piece.set("Start", seconds_to_time(a))
            piece.set("Length", seconds_to_time(b - a))
            piece.set("Offset", seconds_to_time(offset + (a - start)))
            if audible:
                piece.attrib.pop("Muted", None)
                heard += 1
            else:
                piece.set("Muted", "True")
                muted += 1
            pieces.append(piece)

        # Palat alkuperäisen alueen paikalle, jotta tiedosto pysyy luettavana
        # ja alueiden järjestys vastaa aikajanaa.
        for shift, piece in enumerate(pieces):
            track_elem.insert(position + shift, piece)
        track_elem.remove(region)

    return heard, muted


def has_region_children(track_elem) -> bool:
    """Onko jollain alueella lapsielementtejä, jotka pilkkominen pudottaa."""
    for region in track_elem:
        if localname(region) == "Region" and len(region):
            return True
    return False


