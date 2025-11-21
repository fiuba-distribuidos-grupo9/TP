import logging
import uuid
from typing import Any

from controllers.filters.shared.filter import Filter
from middleware.middleware import MessageMiddleware
from middleware.rabbitmq_message_middleware_queue import RabbitMQMessageMiddlewareQueue
from shared.communication_protocol.batch_message import BatchMessage


class FilterTransactionsByYear(Filter):

    # ============================== INITIALIZE ============================== #

    def _build_mom_consumer_using(
        self,
        rabbitmq_host: str,
        consumers_config: dict[str, Any],
    ) -> MessageMiddleware:
        queue_name_prefix = consumers_config["queue_name_prefix"]
        queue_name = f"{queue_name_prefix}-{self._controller_id}"
        return RabbitMQMessageMiddlewareQueue(host=rabbitmq_host, queue_name=queue_name)

    def _build_mom_producer_using(
        self,
        rabbitmq_host: str,
        producers_config: dict[str, Any],
        producer_id: int,
    ) -> MessageMiddleware:
        queue_name_prefix = producers_config["queue_name_prefix"]
        filter_by_hour_queue_name = "to-keep-filtering"
        count_purchases_queue_name = "to-reduce"
        filter_by_hour_queue = RabbitMQMessageMiddlewareQueue(host=rabbitmq_host,queue_name=(f"{queue_name_prefix}-{filter_by_hour_queue_name}-{producer_id}"))
        count_purchases_queue = RabbitMQMessageMiddlewareQueue(host=rabbitmq_host,queue_name=(f"{queue_name_prefix}-{count_purchases_queue_name}-{producer_id}"))
        return [filter_by_hour_queue, count_purchases_queue]

    def __init__(
        self,
        controller_id: int,
        rabbitmq_host: str,
        consumers_config: dict[str, Any],
        producers_config: dict[str, Any],
        years_to_keep: list[int],
    ) -> None:
        super().__init__(
            controller_id,
            rabbitmq_host,
            consumers_config,
            producers_config,
        )

        self._years_to_keep = set(years_to_keep)

    # ============================== PRIVATE - TRANSFORM DATA ============================== #

    def _should_be_included(self, batch_item: dict[str, str]) -> bool:
        created_at = batch_item["created_at"]
        date = created_at.split(" ")[0]
        year = int(date.split("-")[0])

        return year in self._years_to_keep

    # ============================== PRIVATE - MOM SEND/RECEIVE MESSAGES ============================== #

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
            count_producer = self._mom_producers[hash * 2 + 1]
            message = BatchMessage(
                message_type=message.message_type(),
                session_id=message.session_id(),
                message_id=uuid.uuid4().hex,
                controller_id=str(self._controller_id),
                batch_items=batch_items,
            )
            filter_producer.send(str(message))
            count_producer.send(str(message))
