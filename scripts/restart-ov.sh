#!/bin/bash
cd /root/workspace
docker compose up -d
sleep 5
docker ps --format 'table {{.Names}}\t{{.Health}}'