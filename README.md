# Payment Processor

## Запуск

```sh
docker compose up --build -d
```

## Проверка платежа

Запустите локальный приёмник webhook и создайте платёж.

```sh
docker compose up -d webhook

curl -i http://localhost:8000/api/v1/payments \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: local-demo-key' \
  -H 'Idempotency-Key: order-42' \
  -d '{"amount":"1250.50","currency":"RUB","description":"Заказ 42","webhook_url":"http://webhook:8080/ok"}'
```

Ожидаемый ответ — `202 Accepted`. Для проверки статуса подставьте `payment_id` из ответа.

```sh
curl -H 'X-API-Key: local-demo-key' 'http://localhost:8000/api/v1/payments/<payment_id>'
```

После доставки уведомления в поле `webhook_delivered_at` появится время.

## Тесты

```sh
API_PORT=0 docker compose -p payment-processor-check run --build --rm tests
docker compose -p payment-processor-check --profile test down
```

## Остановка

```sh
docker compose --profile test down
```
