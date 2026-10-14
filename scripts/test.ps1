# Run the backend test-suite in a throwaway container using the live source (no rebuild needed).
docker run --rm -v "${PWD}/backend:/app" -v "${PWD}/simulator:/app/simulator" -e PYTHONPATH=/app foodrescue-backend pytest -q @args
