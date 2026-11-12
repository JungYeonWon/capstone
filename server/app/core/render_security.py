from contextvars import ContextVar

# Never render a stored seal in previews, AI requests or unapproved output paths.
seal_authorized = ContextVar("seal_authorized", default=False)
approved_custom_document = ContextVar("approved_custom_document", default=None)
