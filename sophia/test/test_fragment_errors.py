from sophia.backend import fragment_errors
from sophia.backend.routes import evidence, tools
from sophia.backend.services.errors import ServiceError


def test_both_ui_blueprints_share_one_handler_pair():
    for blueprint in (tools.ui, evidence.ui):
        handlers = blueprint.error_handler_spec[None][None]
        assert handlers[ServiceError] is fragment_errors._service_error
        assert handlers[Exception] is fragment_errors._unexpected_error
