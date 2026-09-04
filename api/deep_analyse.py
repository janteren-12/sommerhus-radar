"""
Vercel serverless function: generates the kind of deep, web-researched
investment writeup you'd get from pasting a Boliga link into Claude
directly - comparable sales, tilstandsrapport/el-rapport risk reading,
current financing math, Danish sommerhus tax rules, and a negotiation
recommendation - as a single button on analyser.html.

This is a genuinely different kind of feature from the rest of the site:
every call here spends real money (an Anthropic API call with web search/
web fetch, easily a few minutes of tool use for a report this deep), so
it is NOT wired up to run for free for anyone who finds the URL:

  - ANTHROPIC_API_KEY must be set (Vercel project env var) or every call
    fails with a clear setup error instead of silently doing nothing.
  - ANALYSE_PASSPHRASE gates the endpoint - the caller must send it back
    as the X-Analyse-Key header. This is NOT real security (anyone who
    opens devtools while using the button can see the passphrase go out
    over the network) - it only stops a search engine or a stray link
    from letting strangers spend your API credits by accident.

Restricted to boliga.dk URLs for the same SSRF reason as analyse.py.
"""

import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

import anthropic

ALLOWED_HOSTS = {"www.boliga.dk", "boliga.dk"}

MODEL = "claude-opus-5"

SYSTEM_PROMPT = """\
Du er en erfaren dansk ejendomsinvesteringsanalytiker. Du får et link til en \
Boliga-annonce for et sommerhus/fritidshus og skal skrive en dybdegående, \
tallbaseret investeringsanalyse på dansk - samme niveau som en erfaren \
analytiker ville give en ven, der overvejer at byde på huset.

Fremgangsmåde:
1. Hent selve Boliga-annoncen (web_fetch) for at få adresse, udbudspris, \
   m2, grundstørrelse, byggeår, ejerudgift, offentlig vurdering, evt. \
   dødsbo-status, og find frem til eventuelle tilstandsrapporter/ \
   el-installationsrapporter/salgsopstilling linket fra siden - hent også \
   disse dokumenter, hvis de er tilgængelige, og læs de konkrete skader/ \
   fejl der er noteret.
2. Brug websøgning (web_search) til at finde: sammenlignelige solgte og \
   udbudte huse i samme område (adresse, m2, pris, kr./m2, dato), det \
   aktuelle gennemsnit for kommunen (kr./m2), aktuelle realkreditrenter og \
   bidragssatser for fritidshuse, og de relevante danske skatteregler for \
   sommerhuse (ejendomsavancebeskatningsloven §8 stk. 2, skematisk \
   udlejningsbeskatning, sommerhusloven, evt. selskabsejerskab/ \
   rådighedsbeskatning hvis det er relevant for spørgsmålet).

Strukturér svaret i disse afsnit, med tabeller hvor det giver mening:
- Kort svar (en konklusion i 2-4 sætninger)
- Hvad køber man (nøgletal fra annoncen og rapporterne, med kildehenvisning)
- Markedet lige nu (sammenlignelige salg/udbud, kommunegennemsnit, trend)
- Finansiering (realistisk lånesammensætning, renter, bidrag, netto \
  ejeromkostning pr. år, med de rentesatser du faktisk finder)
- Renoveringsbehov (kun hvis der er en tilstandsrapport at læse ud fra - \
  konkrete skader/fejl og et groft prisoverslag pr. post)
- Skat (kort, og gør opmærksom på at det ikke er skatterådgivning)
- Risici (prioriteret, konkret til DENNE bolig - ikke generiske advarsler)
- Forhandlingsanbefaling (et konkret budforslag med begrundelse)
- Referencer (de kilder du faktisk brugte - annonce, rapporter, søgninger)

Vær konkret og tro mod tallene du finder - gæt aldrig et tal, du ikke kan \
underbygge, og sig klart fra hvis noget ikke kunne findes. Afslut altid med \
en kort disclaimer om at dette ikke er finansiel, juridisk eller \
skattemæssig rådgivning.\
"""


def generate_analysis(target_url):
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    with client.messages.stream(
        model=MODEL,
        max_tokens=64000,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        system=SYSTEM_PROMPT,
        tools=[
            {"type": "web_search_20260209", "name": "web_search", "max_uses": 12},
            {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 8},
        ],
        messages=[
            {
                "role": "user",
                "content": f"Analysér denne bolig til investeringsformål: {target_url}",
            }
        ],
    ) as stream:
        response = stream.get_final_message()

    text_parts = [block.text for block in response.content if block.type == "text"]
    return "\n\n".join(text_parts).strip()


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "X-Analyse-Key")
        self.end_headers()

    def do_GET(self):
        expected_key = os.environ.get("ANALYSE_PASSPHRASE")
        if not expected_key:
            self._send_json(500, {
                "error": "ANALYSE_PASSPHRASE er ikke sat i Vercel - "
                         "funktionen er slået fra indtil den er konfigureret."
            })
            return

        provided_key = self.headers.get("X-Analyse-Key", "")
        if provided_key != expected_key:
            self._send_json(401, {"error": "Forkert eller manglende adgangskode"})
            return

        query = parse_qs(urlparse(self.path).query)
        target_url = (query.get("url") or [None])[0]

        if not target_url:
            self._send_json(400, {"error": "Mangler ?url= parameter"})
            return

        parsed = urlparse(target_url)
        if parsed.hostname not in ALLOWED_HOSTS:
            self._send_json(400, {"error": "Kun boliga.dk-links understøttes"})
            return

        try:
            analysis = generate_analysis(target_url)
        except anthropic.AuthenticationError:
            self._send_json(500, {
                "error": "ANTHROPIC_API_KEY er ikke sat eller ugyldig i Vercel."
            })
            return
        except anthropic.RateLimitError:
            self._send_json(429, {
                "error": "Rate-limit eller opbrugt kvote hos Anthropic - prøv igen senere."
            })
            return
        except anthropic.APIStatusError as error:
            self._send_json(502, {"error": f"Fejl fra Anthropic API: {error}"})
            return
        except anthropic.APIConnectionError as error:
            self._send_json(502, {"error": f"Kunne ikke kontakte Anthropic API: {error}"})
            return

        if not analysis:
            self._send_json(502, {"error": "Fik et tomt svar fra analysen - prøv igen."})
            return

        self._send_json(200, {"analysis": analysis, "model": MODEL})
