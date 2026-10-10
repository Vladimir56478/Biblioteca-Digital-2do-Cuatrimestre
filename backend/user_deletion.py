from fastapi import HTTPException
from sqlalchemy import text


def ensure_no_pending_returns(conn, user_id: int) -> None:
    pending_return = conn.execute(
        text(
            "SELECT 1 FROM Reserva_Ejemplares "
            "WHERE ID_Usuario = :user_id AND Fecha_Expiracion_Reserva >= UTC_TIMESTAMP() "
            "LIMIT 1"
        ),
        {'user_id': user_id},
    ).fetchone()
    if pending_return:
        raise HTTPException(
            status_code=409,
            detail='No se puede eliminar el alumno porque tiene devoluciones pendientes',
        )
