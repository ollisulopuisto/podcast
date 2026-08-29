"""Liitännäisen oma ikkuna omassa prosessissaan — ja sen lukeminen.

    python -m speechmix.editor   # tehtävä stdinissä, tulos stdoutissa

**Miksi tämä on erillinen prosessi.** ``show_editor`` on kutsuttava
pääsäikeestä, ja se **estää** sen kunnes käyttäjä sulkee ikkunan. Isännän
pääsäie ajaa tapahtumasilmukkaa — autoraffkatilla palvelinta, automixerillä
Textualia — eikä sitä voi varata siksi aikaa kun joku katselee liitännäistä.
Lapsen pääsäie on vapaa, ja jos liitännäisen käyttöliittymä kaatuu, se vie
mukanaan vain tämän prosessin.

**Miksi tätä tarvitaan ollenkaan.** Liitännäisen säädettävät parametrit
eivät ole koko sen tila. dxRevive julkaisee neljä parametria — ohitus,
tulo- ja lähtövahvistus, ja Mix — mutta **mallin valinta ei ole yksikään
niistä**. Malli on liitännäisen omassa tilassa, ja siihen pääsee käsiksi
vain liitännäisen omalla käyttöliittymällä. Ilman tätä ajamme aina sitä
mallia, jonka liitännäinen sattuu ottamaan oletuksena, emmekä voi edes
kertoa kummasta on kyse — ja eri malli on eri lopputulos.

Tila luetaan ``raw_state``:sta ja talletetaan asetuksiin base64:nä. Se on
läpinäkymätön tavujono, jonka vain liitännäinen itse osaa tulkita, ja siksi
se on sidottu ``plugin_path``iin: toisen liitännäisen tila ei ole tälle
mitään. Väärä tila ei kaada mitään — ``chain.load_plugin`` sivuuttaa sen ja
jatkaa parametreilla.

**Miksi molemmat päät ovat täällä.** Yhteys on rivipohjaista JSONia
stdoutissa, ja sen jäsennin on osa muotoa: emo joka lukee ensimmäisen
JSON-rivin pitää väliviestiä «opening» tuloksena, ja käyttäjän ikkunaan
jättämä tila katoaa hiljaa. Yksi muoto, yksi jäsennin, molemmat tässä —
kaksi kopiota jäsentimestä olisi sama ajautuminen jota vastaan tämä paketti
on olemassa.
"""

from __future__ import annotations

import base64
import contextlib
import json
import subprocess
import sys
import threading
import traceback
from dataclasses import dataclass, field

from . import chain
from .messages import t

#: Ikkuna saa olla auki tunnin. Se ei ole odotusaika vaan vartija sitä
#: vastaan, että unohtunut ikkuna jää pitämään prosessia hengissä loputtomiin
#: — käyttäjä on ikkunan ääressä niin kauan kuin haluaa.
EDITOR_TIMEOUT = 3600.0


@dataclass
class EditorResult:
    """Mitä käyttäjä jätti ikkunaan: liitännäisen tila ja sen säätimet."""

    state: str = ""
    params: dict = field(default_factory=dict)


def open_editor(
    path: str,
    params: dict | None = None,
    state: str | None = None,
    timeout: float = EDITOR_TIMEOUT,
    log=None,
) -> EditorResult:
    """Avaa liitännäisen ikkunan lapsiprosessissa ja odottaa sen tulosta.

    Polku tarkistetaan **ennen** prosessin käynnistystä: tyhjä polku on
    isännän oma virhe, eikä sitä kannata kertoa vasta lapsen kuoltua.
    """
    if not path:
        raise chain.ChainError(t("audio.plugin_missing", path=path))
    spec = {
        "plugin_path": path,
        "params": dict(params or {}),
        "state": state or None,
    }
    try:
        child = subprocess.run(
            [sys.executable, "-m", "speechmix.editor"],
            input=json.dumps(spec),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise chain.ChainError(t("audio.editor_timeout")) from exc
    return read_result(child.stdout or "", child.stderr or "", log=log)


def read_result(stdout: str, stderr: str, log=None) -> EditorResult:
    """Lapsen tuloste tulokseksi, tai ``ChainError``.

    Rivi joka ei ole JSONia on liitännäisen omaa puhetta — ne kirjoittavat
    stdoutiin surutta — ja se lokitetaan eikä siitä tehdä virhettä.
    """
    say = log if log is not None else _say
    payload: dict = {}
    for line in stdout.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            say(line)
            continue
        if not isinstance(message, dict):
            say(line)
            continue
        if message.get("kind") == "opening":
            # Väliviesti, ei tulos: kertoo vain saiko lapsi nostettua ikkunan
            # eteen. Ilman tätä haaraa se jäisi tulokseksi ja oikea tulos
            # näyttäisi puuttuvan.
            if not message.get("foreground"):
                say(t("audio.editor_behind"))
            continue
        payload = message

    if payload.get("kind") != "done":
        tail = stderr.strip().splitlines()
        raise chain.ChainError(
            payload.get("error") or (tail[-1] if tail else t("audio.editor_failed"))
        )
    return EditorResult(
        state=payload.get("state", "") or "",
        params=payload.get("params") or {},
    )


def _say(message: str) -> None:
    print(message, flush=True)


def _become_an_app() -> bool:
    """Tekee prosessista sellaisen, jonka ikkunan voi nähdä.

    Ilman tätä ikkuna kyllä syntyy — mitattuna 536×392 kohdassa (0, 37) —
    mutta jää isännän ikkunan taakse eikä nouse koskaan eteen, koska pelkkä
    Python-prosessi ei ole macOS:lle käyttöliittymäsovellus. Käyttäjälle se
    näyttää siltä että painike ei tee mitään, ja se on tässä projektissa
    tuttu vikaluokka: tapahtui, ei näkynyt, ei kerrottu.

    ``NSApplicationActivationPolicyRegular`` antaa prosessille Dock-kuvakkeen
    ja oikeuden nousta eteen. pyobjc tulee pywebviewin mukana, mutta sitä ei
    ole pyydetty tässä erikseen, joten puuttuminen ei ole virhe: ikkuna
    aukeaa silloinkin, se on vain etsittävä itse.
    """
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyRegular
    except Exception:
        return False
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    app.activateIgnoringOtherApps_(True)

    def raise_it() -> None:
        # Toinen aktivointi sen jälkeen kun ikkuna on oikeasti olemassa:
        # ensimmäinen tapahtuu ennen kuin liitännäinen on piirtänyt mitään.
        # ``show_editor`` ajaa tällä välin viestisilmukkaa, joten kutsu menee
        # perille.
        import time

        time.sleep(1.0)
        with contextlib.suppress(Exception):
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    threading.Thread(target=raise_it, daemon=True).start()
    return True


def main() -> int:
    """Avaa ikkunan ja palauttaa tilan, jonka käyttäjä siihen jätti."""
    spec = json.load(sys.stdin)

    def emit(payload: dict) -> None:
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()

    try:
        plugin = chain.load_plugin(
            spec["plugin_path"], spec.get("params"), spec.get("state")
        )
        if plugin is None:
            emit({"kind": "failed", "error": t("audio.plugin_missing", path="")})
            return 1
        # Ikkuna eteen ennen kuin se avataan. Avaus estää pääsäikeen, joten
        # tämän jälkeen ei ehdi tehdä mitään.
        emit({"kind": "opening", "foreground": _become_an_app()})
        plugin.show_editor()
        emit(
            {
                "kind": "done",
                "state": base64.b64encode(bytes(plugin.raw_state)).decode("ascii"),
                # Parametrit palautetaan myös: käyttäjä on voinut kääntää
                # Mixiä samassa ikkunassa, ja liukusäätimen on seurattava.
                "params": chain.read_parameters(plugin),
            }
        )
        return 0
    except Exception as exc:  # pragma: no cover - riippuu liitännäisestä
        emit({"kind": "failed", "error": f"{exc}", "trace": traceback.format_exc()})
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
