# Symmy Tasker: ERP → E-shop Sync

Synchronizační můstek mezi ERP systémem a e-shopem. Běží jako Celery task v Django.

## Architektura

```
erp_data.json  →  Celery Worker (sync_products)  →  E-shop API
                         ↕
                    PostgreSQL (delta sync hash)
                         ↑
                    Celery Beat (každých 10 min)
```

**Datový tok:**

1. Načtení `erp_data.json` (simulace ERP)
2. Deduplikace SKU (poslední výskyt vyhrává)
3. Validace (platné SKU, kladná cena, neprázdné sklady)
4. Transformace — součet skladů, +21 % DPH, default barva `"N/A"`
5. Delta sync — SHA-256 hash porovnán s DB, posílají se jen změny
6. API volání — POST (nový) / PATCH (existující), rate-limiting 5 req/s, retry na 429

## Spuštění

```bash
docker-compose up --build
```

Migrace proběhnou automaticky. Po startu:
- Web: http://localhost:8000
- Sync běží automaticky každých 10 minut přes Celery Beat

Ruční spuštění:

```bash
docker-compose exec web python manage.py shell -c "from integrator.tasks import sync_products; print(sync_products.delay().get(timeout=30))"
```

## Testy

API je fiktivní (`https://api.fake-eshop.cz/v1`) — v testech mockované přes `responses`.

```bash
# lokálně (SQLite fallback)
pip install -r requirements.txt
python manage.py test integrator -v 2

# v Dockeru
docker-compose exec web python manage.py test integrator -v 2
```

29 testů, 100% code coverage: validace, transformace, deduplikace, hashování, API komunikace (POST/PATCH/retry 429), delta sync, error handling.

## E-shop API

| Metoda | Endpoint | Popis |
|---|---|---|
| POST | `/products/` | Nový produkt |
| PATCH | `/products/{sku}/` | Update existujícího |

Base URL: `https://api.fake-eshop.cz/v1`, auth header `X-Api-Key: symma-secret-token`
