#!/bin/sh
set -e

echo "Waiting for database..."
while ! python -c "import socket; socket.create_connection(('db', 5432), timeout=1)" 2>/dev/null; do
    sleep 1
done

if [ "$RUN_MIGRATIONS" = "true" ]; then
    echo "Running migrations..."
    python manage.py migrate --noinput
fi

exec "$@"
