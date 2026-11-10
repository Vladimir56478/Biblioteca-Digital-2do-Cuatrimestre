"""Reglas de integridad para desactivar cuentas sin perder préstamos activos."""

from fastapi import HTTPException
from sqlalchemy import text


def ensure_no_active_loans(conn, user_id: int) -> None:
    """Impide inactivar una cuenta que aún participa en un préstamo activo.

    Se revisan ambos roles del Cuaderno Diario (responsable y alumno que retira)
    y el rol de responsable de la Ficha Domiciliaria. La conexión recibida forma
    parte de la transacción que realiza la operación sobre la cuenta.
    """
    active_loan = conn.execute(
        text(
            "SELECT 1 FROM cuaderno_diario "
            "WHERE ID_Responsable = :user_id AND Estado = 'Activo' "
            "UNION ALL "
            "SELECT 1 FROM cuaderno_diario "
            "WHERE ID_Retira = :user_id AND Estado = 'Activo' "
            "UNION ALL "
            "SELECT 1 FROM ficha_domiciliaria "
            "WHERE ID_Responsable = :user_id AND Estado = 'Activo' "
            "LIMIT 1"
        ),
        {'user_id': user_id},
    ).fetchone()
    if active_loan:
        raise HTTPException(
            status_code=409,
            detail='No se puede inactivar al alumno porque tiene préstamos activos pendientes de devolución',
        )
