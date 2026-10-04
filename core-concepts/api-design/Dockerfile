FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend ./
RUN npm install && npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY --from=ui /ui/dist ./src/static
RUN python -m grpc_tools.protoc -I src --python_out=src --grpc_python_out=src src/inventory.proto \
 && python -c "from pathlib import Path; p=Path('src/inventory_pb2_grpc.py'); t=p.read_text(); t=t.replace('import inventory_pb2 as inventory__pb2','from src import inventory_pb2 as inventory__pb2'); t=t.replace('\nimport inventory_pb2\n','\nfrom src import inventory_pb2\n'); p.write_text(t)"

EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
