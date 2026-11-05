FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir boto3==1.43.123
COPY app.py .
EXPOSE 8080
CMD ["python", "app.py"]
