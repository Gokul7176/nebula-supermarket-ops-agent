from contextvars import ContextVar

current_chat_id_var: ContextVar[str] = ContextVar("current_chat_id", default="default")
current_user_message_var: ContextVar[str] = ContextVar("current_user_message", default="")
