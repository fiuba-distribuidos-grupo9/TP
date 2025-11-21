from typing import Any
import uuid

from controllers.filters.shared.filter import Filter
from middleware.middleware import MessageMiddleware
from middleware.rabbitmq_message_middleware_queue import (
    RabbitMQMessageMiddlewareQueue,
)
from shared.communication_protocol.batch_message import BatchMessage

class FilterTransactionsByHour(Filter):

    # ============================== INITIALIZE ============================== #

    def _build_mom_consumer_using(
        self,
        rabbitmq_host: str,
        consumers_config: dict[str, Any],
    ) -> MessageMiddleware:
        queue_name_prefix = consumers_config["queue_name_prefix"]
        queue_type = consumers_config["queue_type"]
        queue_name = f"{queue_name_prefix}-{queue_type}-{self._controller_id}"
        return RabbitMQMessageMiddlewareQueue(host=rabbitmq_host, queue_name=queue_name)

    def _build_mom_producer_using(
        self,
        rabbitmq_host: str,
        producers_config: dict[str, Any],
        producer_id: int,
    ) -> MessageMiddleware:
        queue_name_prefix = producers_config["queue_name_prefix"]
        map_queue_name = "to-map"
        filter_queue_name = "to-keep-filtering"
        filter_queue = RabbitMQMessageMiddlewareQueue(host=rabbitmq_host, queue_name=(f"{queue_name_prefix}-{filter_queue_name}-{producer_id}"))
        map_queue = RabbitMQMessageMiddlewareQueue(host=rabbitmq_host, queue_name=(f"{queue_name_prefix}-{map_queue_name}-{producer_id}"))
        return [filter_queue, map_queue]

    def __init__(
        self,
        controller_id: int,
        rabbitmq_host: str,
        consumers_config: dict[str, Any],
        producers_config: dict[str, Any],
        min_hour: int,
        max_hour: int,
    ) -> None:
        super().__init__(
            controller_id,
            rabbitmq_host,
            consumers_config,
            producers_config,
        )

        self._min_hour = min_hour
        self._max_hour = max_hour

    # ============================== PRIVATE - TRANSFORM DATA ============================== #

    def _should_be_included(self, batch_item: dict[str, str]) -> bool:
        created_at = batch_item["created_at"]
        time = created_at.split(" ")[1]
        hour = int(time.split(":")[0])

        return self._min_hour <= hour and hour < self._max_hour

    # ============================== PRIVATE - SEND DATA ============================== #

    def _mom_send_message_to_next(self, message: BatchMessage) -> None:
        batch_items_by_hash: dict[int, list] = {}
        # [IMPORTANT] this must consider the next controller's grouping key
        sharding_key = "user_id"

        next_controllers = len(self._mom_producers) // 2

        for batch_item in message.batch_items():
            if batch_item[sharding_key] == "":
                # [IMPORTANT] If sharding value is empty, the hash will fail
                # but we are going to assign it to the first reducer anyway
                hash = 0
                batch_items_by_hash.setdefault(hash, [])
                batch_items_by_hash[hash].append(batch_item)
                continue
            sharding_value = int(float(batch_item[sharding_key]))
            batch_item[sharding_key] = str(sharding_value)

            hash = sharding_value % next_controllers
            batch_items_by_hash.setdefault(hash, [])
            batch_items_by_hash[hash].append(batch_item)

        for hash, batch_items in batch_items_by_hash.items():
            filter_producer = self._mom_producers[hash * 2]
            map_producer = self._mom_producers[hash * 2 + 1]
            message = BatchMessage(
                message_type=message.message_type(),
                session_id=message.session_id(),
                message_id=uuid.uuid4().hex,
                controller_id=str(self._controller_id),
                batch_items=batch_items,
            )
            filter_producer.send(str(message))
            map_producer.send(str(message))