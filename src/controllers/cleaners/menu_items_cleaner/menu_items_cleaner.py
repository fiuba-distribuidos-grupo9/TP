from typing import Any
import uuid

from controllers.cleaners.shared.cleaner import Cleaner
from middleware.middleware import MessageMiddleware
from middleware.rabbitmq_message_middleware_queue import RabbitMQMessageMiddlewareQueue
from shared.communication_protocol.batch_message import BatchMessage


class MenuItemsCleaner(Cleaner):

    # ============================== INITIALIZE ============================== #

    def _build_mom_producer_using(
        self, rabbitmq_host: str, producers_config: dict[str, Any], producer_id: int
    ) -> MessageMiddleware:
        queue_name_prefix = producers_config["queue_name_prefix"]
        queue_name_a = f"{queue_name_prefix}-q21-{producer_id}"
        queue_name_b = f"{queue_name_prefix}-q22-{producer_id}"
        queue_a = RabbitMQMessageMiddlewareQueue(host=rabbitmq_host,queue_name=queue_name_a)
        queue_b = RabbitMQMessageMiddlewareQueue(host=rabbitmq_host,queue_name=queue_name_b)
        return [queue_a, queue_b]

    # ============================== PRIVATE - ACCESSING ============================== #

    def _columns_to_keep(self) -> list[str]:
        return [
            "item_id",
            "item_name",
        ]

    # ============================== PRIVATE - MOM SEND/RECEIVE MESSAGES ============================== #

    def _mom_send_message_to_next(self, message: BatchMessage) -> None:
        mom_producer = self._mom_producers[self._current_producer_id]
        mom_producer.send(str(message))
        mom_producer = self._mom_producers[self._current_producer_id+1]
        mom_producer.send(str(message))

        self._current_producer_id += 2
        if self._current_producer_id >= len(self._mom_producers):
            self._current_producer_id = 0
