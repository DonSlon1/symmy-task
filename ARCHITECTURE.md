# Architektura: Product Sync Integrator

## Jak je kód rozdělený a proč

### Před refactoringem

Vše bylo v jednom souboru `integrator/tasks.py` (168 řádků):

```
integrator/
    tasks.py      ← validace, transformace, HTTP, DB, Celery — všechno
    models.py
    tests.py      ← jeden soubor, 366 řádků
core/
    settings.py   ← jeden soubor, dev i prod dohromady
```

**Problémy:**
- Nelze vyměnit ERP zdroj nebo API klienta bez přepisování `tasks.py`
- Pro 1000 produktů se dělá 2000 DB dotazů (SELECT + UPDATE/INSERT na každý)
- Testy nelze spouštět izolovaně (vše v jednom souboru)
- Settings nemají oddělení dev/prod

### Po refactoringu

```
integrator/
    transforms.py              ← čisté funkce (žádné I/O, žádný Django)
    sync.py                    ← SyncOrchestrator — bulk DB + hlavní smyčka
    sources/
        base.py                ← BaseSource ABC — kontrakt pro zdroje dat
        json_source.py         ← JsonFileSource — načtení z JSON souboru
    clients/
        base.py                ← BaseClient ABC — kontrakt pro API klienty
        eshop_client.py        ← EshopClient — POST/PATCH + retry na 429
    tasks.py                   ← tenký wrapper — Celery task, 42 řádků
    tests/
        test_transforms.py     ← validace, transformace, deduplikace, hash
        test_sources.py        ← načtení dat z JSON
        test_clients.py        ← HTTP komunikace, retry logika
        test_sync.py           ← delta sync, bulk operace, chyby
        test_models.py         ← model ProductSyncState
        test_tasks.py          ← zpětná kompatibilita wrapperů
core/
    settings/
        base.py                ← sdílená konfigurace, environs
        dev.py                 ← SQLite, DEBUG=True
        prod.py                ← Postgres, security headers, SECRET_KEY povinný
```

### Proč právě takhle?

**Princip: oddělení podle odpovědnosti (Separation of Concerns)**

| Modul | Odpovědnost | Závislosti |
|---|---|---|
| `transforms.py` | Čistá byznys logika | Žádné (jen stdlib) |
| `sources/` | Odkud data přichází | Django settings |
| `clients/` | Kam data odchází | Django settings, requests |
| `sync.py` | Orchestrace + DB | Django ORM, transforms |
| `tasks.py` | Celery entry point | Vše výše |

**Klíčový benefit:** `SyncOrchestrator` nepotřebuje vědět, odkud data přichází ani kam jdou. Dostane `source` a `client` jako parametry — klasický Strategy pattern.

```
┌─────────────────────────────────────────────────────────────┐
│  tasks.py  (Celery entry point)                             │
│                                                             │
│  settings.SYNC_SOURCE_CLASS ──► import_string() ──► source  │
│  settings.SYNC_CLIENT_CLASS ──► import_string() ──► client  │
│                                         │            │      │
│                                         ▼            ▼      │
│                              SyncOrchestrator(source, client)│
└────────────────────────────────┬────────────────────────────┘
                                 │
          ┌──────────────────────┼──────────────────────┐
          ▼                      ▼                      ▼
   source.load()          transforms.*          client.send()
   ┌────────────┐    ┌──────────────────┐    ┌──────────────┐
   │JsonFile    │    │ deduplicate()    │    │ EshopClient  │
   │Source      │    │ validate()       │    │  POST/PATCH  │
   │            │    │ transform()      │    │  retry 429   │
   │(nebo jiný) │    │ compute_hash()   │    │(nebo jiný)   │
   └────────────┘    └──────────────────┘    └──────────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  Django ORM      │
                    │  bulk_create()   │
                    │  bulk_update()   │
                    │  filter(sku__in) │
                    └──────────────────┘
```

---

## Jak přidat nový ERP nebo API

### Nový ERP zdroj (např. HTTP API místo JSON souboru)

**1. Vytvořit třídu:**

```python
# integrator/sources/http_erp.py
import requests
from django.conf import settings
from .base import BaseSource

class HttpErpSource(BaseSource):
    def load(self) -> list[dict]:
        resp = requests.get(
            settings.ERP_API_URL,
            headers={'Authorization': f'Bearer {settings.ERP_API_TOKEN}'},
        )
        resp.raise_for_status()
        return resp.json()
```

**2. Změnit setting** (žádná úprava kódu):

```python
# core/settings/prod.py
SYNC_SOURCE_CLASS = 'integrator.sources.http_erp.HttpErpSource'
```

nebo přes env var:
```bash
SYNC_SOURCE_CLASS=integrator.sources.http_erp.HttpErpSource
```

Hotovo. `SyncOrchestrator`, `tasks.py` — nic se nemění.

### Nový API klient (např. jiný e-shop s REST API)

**1. Vytvořit třídu:**

```python
# integrator/clients/customer_b.py
import requests
from .base import BaseClient

class CustomerBClient(BaseClient):
    def make_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            'Authorization': 'Bearer customer-b-token',
            'Accept': 'application/json',
        })
        return session

    def send(self, session, payload, is_update=False):
        # Customer B má jiné API — vždy PUT na /{sku}
        url = f"https://api.customer-b.com/products/{payload['sku']}"
        resp = session.put(url, json=payload)
        resp.raise_for_status()
        return resp
```

**2. Změnit setting:**

```python
SYNC_CLIENT_CLASS = 'integrator.clients.customer_b.CustomerBClient'
```

### Proč je to lepší než předtím?

| Aspekt | Před | Po |
|---|---|---|
| Přidat nový ERP | Přepsat `load_erp_data()` v tasks.py | Nový soubor + setting |
| Přidat nové API | Přepsat `send_to_eshop()` v tasks.py | Nový soubor + setting |
| Testovat zdroj izolovaně | Nelze (vše v jednom souboru) | Ano (`test_sources.py`) |
| Zpětná kompatibilita | — | Re-exporty v `tasks.py` |

---

## Optimalizace DB operací

### Před: 2N dotazů (2000 pro 1000 produktů)

```python
# Starý kód — uvnitř for cyklu pro KAŽDÝ produkt:
for raw in raw_data:
    # Dotaz 1: SELECT — existuje tento produkt?
    sync_state = ProductSyncState.objects.get(sku=sku)       # ← 1 SELECT

    # Dotaz 2: INSERT nebo UPDATE
    ProductSyncState.objects.update_or_create(sku=sku, ...)  # ← 1 INSERT/UPDATE
```

Pro 1000 produktů = 2000 SQL dotazů. Každý dotaz má overhead (parse, plan, network roundtrip).

### Po: 3 dotazy (vždy, bez ohledu na počet produktů)

```python
# Nový kód v SyncOrchestrator.run():

# Dotaz 1: Jeden SELECT pro VŠECHNY produkty najednou
existing_states = {
    state.sku: state
    for state in ProductSyncState.objects.filter(sku__in=all_skus)
}
# → SQL: SELECT * FROM integrator_productsyncstate WHERE sku IN ('SKU-001', 'SKU-002', ...)

# Porovnání hashů probíhá v Pythonu (dict lookup = O(1))
existing = existing_states.get(sku)
if existing and existing.data_hash == data_hash:
    # skip — žádný SQL dotaz

# Dotaz 2: Jeden INSERT pro všechny nové produkty
ProductSyncState.objects.bulk_create(to_create)
# → SQL: INSERT INTO ... VALUES (...), (...), (...), ...

# Dotaz 3: Jeden UPDATE pro všechny změněné produkty
ProductSyncState.objects.bulk_update(to_update, ['data_hash', 'last_synced_at'])
# → SQL: UPDATE ... SET data_hash = CASE WHEN sku = 'SKU-001' THEN ... END, ...
```

### Pozor na auto_now

`last_synced_at = models.DateTimeField(auto_now=True)` funguje pouze při volání
`model.save()`. Metody `bulk_create()` a `bulk_update()` neprochází přes `save()`,
takže `auto_now` se neaktivuje. Řešení:

```python
now = timezone.now()
# Ručně nastavit timestamp před bulk operací:
existing.last_synced_at = now           # pro update
ProductSyncState(sku=sku, ..., last_synced_at=now)  # pro create
```

### Výsledek

| Metrika | Před | Po | Zlepšení |
|---|---|---|---|
| SQL dotazy (1000 produktů) | ~2000 | 3 | **~660×** |
| SQL dotazy (10 000 produktů) | ~20 000 | 3 | **~6600×** |
| Výkon | Lineární s počtem produktů | Konstantní (DB) | Škáluje |

---

## Další provedené změny

**Settings split (base/dev/prod):**
- `base.py` — sdílená konfigurace, `environs` pro env vars
- `dev.py` — SQLite, `DEBUG=True`, insecure SECRET_KEY (ok pro lokální vývoj)
- `prod.py` — Postgres, `SECRET_KEY` povinný (bez defaultu = fail-fast), security headers

**Cleanup:**
- Odstraněn `djangorestframework` z requirements (nikde se nepoužíval)
- Odstraněn `bind=True` z Celery tasku (`self` se nikde nepoužíval, `self.retry()` nevolalo)
- Přidán `coverage` do requirements

---

## Možná další vylepšení (neimplementováno)

1. **Batch API volání** — pokud e-shop API podporuje bulk endpoint (POST /products/batch),
   dalo by se posílat 50-100 produktů najednou místo po jednom. To by zredukovalo i HTTP
   overhead.

2. **Async HTTP** — `httpx` nebo `aiohttp` místo `requests` by umožnily posílat více
   požadavků paralelně (respektujíc rate limit), což by zrychlilo sync u velkých datasetů.

3. **Konfigurovatelný rate limit per-client** — momentálně je `RATE_LIMIT` globální setting.
   Pokud různí klienti mají různé limity, mohlo by to být atributem `BaseClient`.

4. **Idempotentní bulk DB zápis** — pokud `send_to_eshop` uspěje ale aplikace spadne před
   `bulk_create`, při dalším syncu se produkt pošle znovu (protože stav není v DB). Řešení:
   zapisovat do DB po menších batchích, ne na konci celého syncu.

5. **Monitoring** — přidat metriky (Prometheus/StatsD) pro počet synced/skipped/errors
   per run, aby se daly sledovat trendy a detekovat problémy dřív než z logů.
