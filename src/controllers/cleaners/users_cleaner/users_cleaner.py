import logging
import uuid
from typing import Any

from controllers.cleaners.shared.cleaner import Cleaner
from middleware.middleware import MessageMiddleware
from middleware.rabbitmq_message_middleware_queue import RabbitMQMessageMiddlewareQueue
from shared.communication_protocol.batch_message import BatchMessage


class UsersCleaner(Cleaner):

    # ============================== INITIALIZE ============================== #

    def _build_mom_producer_using(
        self, rabbitmq_host: str, producers_config: dict[str, Any], producer_id: int
    ) -> MessageMiddleware:
        queue_name_prefix = producers_config["queue_name_prefix"]
        queue_name = f"{queue_name_prefix}-{producer_id}"
        return RabbitMQMessageMiddlewareQueue(host=rabbitmq_host, queue_name=queue_name)

    # ============================== PRIVATE - ACCESSING ============================== #

    def _columns_to_keep(self) -> list[str]:
        return [
            "user_id",
            "birthdate",
        ]

    # ============================== PRIVATE - MOM SEND/RECEIVE MESSAGES ============================== #

    def _mom_send_message_to_next(self, message: BatchMessage) -> None:
        batch_items_by_hash: dict[int, list] = {}
        # [IMPORTANT] this must consider the next controller's grouping key
        sharding_key = "user_id"

        for batch_item in message.batch_items():
            if batch_item[sharding_key] == "":
                logging.warning(
                    f"action: invalid_{sharding_key} | {sharding_key}: {batch_item[sharding_key]} | result: skipped"
                )
                continue
            sharding_value = int(float(batch_item[sharding_key]))
            batch_item[sharding_key] = str(sharding_value)

            hash = sharding_value % len(self._mom_producers)
            batch_items_by_hash.setdefault(hash, [])
            batch_items_by_hash[hash].append(batch_item)

        for hash, batch_items in batch_items_by_hash.items():
            mom_producer = self._mom_producers[hash]
            message = BatchMessage(
                message_type=message.message_type(),
                session_id=message.session_id(),
                message_id=uuid.uuid4().hex,
                controller_id=str(self._controller_id),
                batch_items=batch_items,
            )
            mom_producer.send(str(message))
