from controllers.output_builders.shared.query_output_builder import QueryOutputBuilder
from shared.communication_protocol import communication_protocol


class Query3XOutputBuilder(QueryOutputBuilder):

    # ============================== PRIVATE - INTERFACE ============================== #

    def _columns_to_keep(self) -> list[str]:
        return ["year_half_created_at", "store_name", "tpv"]

    def _output_message_type(self) -> str:
        return communication_protocol.QUERY_RESULT_3X_MSG_TYPE
