from typing import Any

from controllers.filters.shared.filter import Filter
from middleware.middleware import MessageMiddleware
from middleware.rabbitmq_message_middleware_queue import RabbitMQMessageMiddlewareQueue


class FilterTransactionsByFinalAmount(Filter):

    # ============================== INITIALIZE ============================== #

    def _build_mom_consumer_using(
        self,
        rabbitmq_host: str,
        consumers_config: dict[str, Any],
    ) -> MessageMiddleware:
        queue_name_prefix = consumers_config["queue_name_prefix"]
        queue_type = consumers_config["queue_type"]
        queue_name = f"{queue_name_prefix}-{queue_type}-{self._controller_id}"
        return RabbitMQMessageMiddlewareQueue(host=rabbitmq_host,queue_name=queue_name)

    def _build_mom_producer_using(
        self,
        rabbitmq_host: str,
        producers_config: dict[str, Any],
        producer_id: int,
    ) -> MessageMiddleware:
        queue_name_prefix = producers_config["queue_name_prefix"]
        queue_name = f"{queue_name_prefix}-{producer_id}"
        return [RabbitMQMessageMiddlewareQueue(host=rabbitmq_host, queue_name=queue_name)]

    def __init__(
        self,
        controller_id: int,
        rabbitmq_host: str,
        consumers_config: dict[str, Any],
        producers_config: dict[str, Any],
        min_final_amount: float,
    ) -> None:
        super().__init__(
            controller_id,
            rabbitmq_host,
            consumers_config,
            producers_config,
        )

        self._min_final_amount = min_final_amount

    # ============================== PRIVATE - TRANSFORM DATA ============================== #

    def _should_be_included(self, batch_item: dict[str, str]) -> bool:
        final_amount = float(batch_item["final_amount"])
        return final_amount >= self._min_final_amount
