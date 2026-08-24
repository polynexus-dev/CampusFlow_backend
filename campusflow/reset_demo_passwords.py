import os
import sys
import django

# Set up Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "campusflow.settings")
django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django_tenants.utils import schema_context  # noqa: E402


def _print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="ignore").decode("ascii"))


def reset_passwords(schema_name="demo", new_password="admin123"):
    _print(
        f"🔄 Resetting all user passwords in schema '{schema_name}' to "
        f"'{new_password}'..."
    )

    with schema_context(schema_name):
        users = User.objects.all()
        total_users = users.count()

        if total_users == 0:
            _print(f"⚠️ No users found in schema '{schema_name}'.")
            return

        for user in users:
            user.set_password(new_password)
            user.save()

        _print(
            f"✅ Successfully reset passwords for {total_users} user(s) in tenant "
            f"'{schema_name}'."
        )


if __name__ == "__main__":

    schema = sys.argv[1] if len(sys.argv) > 1 else "demo"
    password = sys.argv[2] if len(sys.argv) > 2 else "admin123"
    reset_passwords(schema, password)
