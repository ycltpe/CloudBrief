from datetime import datetime

from sqlalchemy.orm import Session

from app.stores.db import SystemSetting, get_session_factory


class SettingsStore:
    def get_session(self) -> Session:
        return get_session_factory()()

    def get_all(self) -> list[SystemSetting]:
        with self.get_session() as session:
            return session.query(SystemSetting).order_by(SystemSetting.key).all()

    def get(self, key: str) -> SystemSetting | None:
        with self.get_session() as session:
            return session.query(SystemSetting).filter(SystemSetting.key == key).first()

    def set(
        self,
        key: str,
        value: str,
        updated_by: int | None = None,
        description: str | None = None,
    ) -> SystemSetting:
        with self.get_session() as session:
            row = session.query(SystemSetting).filter(SystemSetting.key == key).first()
            if row is None:
                row = SystemSetting(
                    key=key,
                    value=value,
                    description=description or "",
                    updated_by=updated_by,
                )
                session.add(row)
            else:
                row.value = value
                row.updated_by = updated_by
                if description is not None:
                    row.description = description
                row.updated_at = datetime.utcnow()
            session.commit()
            session.refresh(row)
            return row

    def set_many(
        self,
        items: dict[str, str],
        updated_by: int | None = None,
    ) -> list[SystemSetting]:
        results = []
        for key, value in items.items():
            results.append(self.set(key, value, updated_by=updated_by))
        return results

    def delete(self, key: str) -> None:
        with self.get_session() as session:
            session.query(SystemSetting).filter(SystemSetting.key == key).delete()
            session.commit()
