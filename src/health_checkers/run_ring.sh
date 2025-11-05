#!/bin/bash
docker network create ringnet 2>/dev/null || true

docker run -d --name hc1_container --network ringnet \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e NODE_ID=1 -e NODE_NAME=hc-1 -e LISTEN_PORT=9101 \
  -e RING_PEERS="2@hc2_container:9102,3@hc3_container:9103" \
  -e HEARTBEAT_INTERVAL_MS=500 -e HEARTBEAT_TIMEOUT_MS=1500 \
  -e SUSPECT_GRACE_MS=5000 \
  -e MODE=auto tp-health-checker

docker run -d --name hc2_container --network ringnet \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e NODE_ID=2 -e NODE_NAME=hc-2 -e LISTEN_PORT=9102 \
  -e RING_PEERS="1@hc1_container:9101,3@hc3_container:9103" \
  -e HEARTBEAT_INTERVAL_MS=500 -e HEARTBEAT_TIMEOUT_MS=1500 \
  -e SUSPECT_GRACE_MS=5000 \
  -e MODE=auto tp-health-checker

docker run -d --name hc3_container --network ringnet \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e NODE_ID=3 -e NODE_NAME=hc-3 -e LISTEN_PORT=9103 \
  -e RING_PEERS="1@hc1_container:9101,2@hc2_container:9102" \
  -e HEARTBEAT_INTERVAL_MS=500 -e HEARTBEAT_TIMEOUT_MS=1500 \
  -e SUSPECT_GRACE_MS=5000 \
  -e MODE=auto tp-health-checker


echo "All health checkers running. Use: docker logs -f $(docker ps -q --filter ancestor=tp-health-checker)"
