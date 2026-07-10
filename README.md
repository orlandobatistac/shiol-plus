# SHIOL+ v9 — Strategy Analytics Engine

Motor analítico para evaluación de estrategias de lotería.

## Arquitectura

```
engine/       → Python (antes "lab/") — estrategias, evaluación, pesos.
                 Corre en un Cloudflare Container (ver docs/adr/0001-...).
schema/       → SQL schema para Cloudflare D1
frontend/     → servido como Workers Static Assets (mismo Worker que la API)
data/         → CSV histórico de draws (no va a git si es .db)
```

> Nota: esta sección está desactualizada respecto al resto del README (Cloudflare
> Pages, "Claude Cowork scheduled tasks" como cómputo, etc.) — ver
> `docs/adr/0001-python-first-engine-docker-cloudflare-standby.md` y `TODO.md`
> para la arquitectura vigente. Pendiente una revisión completa de este archivo.

## Stack

| Capa | Tecnología |
|------|-----------|
| Cómputo | Claude (Cowork scheduled tasks) |
| Base de datos | Cloudflare D1 (SQLite edge) |
| API | Cloudflare Worker |
| Frontend | Cloudflare Pages (HTML/CSS/JS) |
| Assets | Cloudflare R2 (solo estáticos) |

## Flujo

1. **Lab local**: backtest de estrategias vs histórico → seleccionar las mejores
2. **Pipeline auto** (lun/mié/sáb 11:10 PM ET): fetch draw → evaluar → actualizar pesos → escribir D1
3. **Frontend**: Cloudflare Pages lee D1 via Worker → dashboard actualizado

## Lotteries soportadas

- [x] Powerball (Mon/Wed/Sat)
- [ ] Mega Millions (futuro)

## Estrategias activas

| Estrategia | Tipo | Estado |
|-----------|------|--------|
| frequency_weighted | Estadística histórica | active |
| cooccurrence | Análisis de pares | active |
| range_balanced | Distribución por rangos | active |
| coverage_optimizer | Anti-solapamiento | active |
| xgboost_ml | ML — XGBoost | active |
| hybrid_ensemble | XGBoost + Cooccurrence | active |
| intelligent_scoring | Multi-criterio | active |
| random_baseline | Control científico | active |
