FROM python:3.12-slim
WORKDIR /app
COPY server.py render.py ./
COPY public ./public
ENV PYTHONUNBUFFERED=1 DATA_DIR=/data
VOLUME /data
EXPOSE 8080
ENV PORT=8080
CMD ["python3", "server.py"]
