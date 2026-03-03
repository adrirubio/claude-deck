# Usage API

Query token usage, costs, and billing blocks.

## Endpoints

### Get Summary

```http
GET /api/v1/usage/summary?project_path={path}
```

Returns overall usage statistics.

### Get Daily Usage

```http
GET /api/v1/usage/daily?project_path={path}&start_date={date}&end_date={date}
```

Returns daily breakdown of token usage and costs.

### Get Session Usage

```http
GET /api/v1/usage/sessions?project_path={path}&limit={n}
```

Returns per-session usage data.

### Get Monthly Usage

```http
GET /api/v1/usage/monthly?project_path={path}&start_month={month}&end_month={month}
```

Returns monthly aggregated usage.

### Get Billing Blocks

```http
GET /api/v1/usage/blocks?project_path={path}&recent={bool}&active={bool}
```

Returns 5-hour billing block data.

### Invalidate Cache

```http
POST /api/v1/usage/cache/invalidate?cache_type={type}&project_path={path}
```

Forces re-computation of cached usage data.
