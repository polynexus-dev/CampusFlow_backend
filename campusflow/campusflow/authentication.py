from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from django_tenants.utils import schema_context
from django.db import connection

class CrossTenantJWTAuthentication(JWTAuthentication):
    """
    Custom JWT Authentication that allows the public superuser to
    authenticate against any tenant schema using their public token.
    """
    def get_user(self, validated_token):
        # 0. Security Check: Ensure the token was issued for this specific tenant
        token_tenant = validated_token.get('tenant_schema')
        current_tenant = connection.schema_name

        try:
            # 1. Normal behavior: try to find the user in the current schema (e.g. mit_college)
            user = super().get_user(validated_token)
            
            # If the user is NOT a superuser, their token MUST match the current schema
            if not user.is_superuser:
                if token_tenant != current_tenant:
                     raise AuthenticationFailed(
                         "This token was issued for a different college and cannot be used here.",
                         code='tenant_mismatch'
                     )
            return user
        except AuthenticationFailed as e:
            # 2. If the user isn't found in the tenant schema, check if we are already in the public schema
            if connection.schema_name == 'public':
                raise e
            
            # 3. If we are in a tenant schema, switch context to the public schema to check there
            with schema_context('public'):
                try:
                    user = super().get_user(validated_token)
                    # 4. Only allow cross-schema access if the user is a superuser
                    if user.is_superuser:
                        return user
                except AuthenticationFailed:
                    pass
            
            # 5. If they weren't found in the public schema either (or aren't a superuser), raise the original error
            raise e
