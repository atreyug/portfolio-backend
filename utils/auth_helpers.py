from models.manager import Manager


def build_token_data(manager: Manager) -> dict:
    return {
        "manager_id": str(manager.id),
        "email": manager.email,
        "name": manager.name,
    }
