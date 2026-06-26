# Base image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    postgresql-client \
    gdal-bin \
    libgdal-dev \
    binutils \
    libproj-dev \
    libglib2.0-0 \
    libgl1 \
    libxcb1 \
    libx11-xcb1 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Set GDAL environment variables
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

# Set work directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy project
COPY . .

# Backup clean migration files (tracked in git) to a safe place in the image
RUN cp -r campusflow_app/migrations /tmp/clean_migrations

EXPOSE 8000
