#!/bin/bash
docker compose down
docker compose build --no-cache amadeuscomic-app
docker compose up -d
sleep 5
docker ps
