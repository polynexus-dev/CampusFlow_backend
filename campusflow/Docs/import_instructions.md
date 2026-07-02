# Instructions for Importing and Using the CampusFlow Postman Collection

Follow these steps to import the collection and environment into Postman and verify your API.

---

## Step 1 — Import files into Postman

1.  Open your Postman application.
2.  Click the **Import** button in the top left corner (or press `Ctrl + O` / `Cmd + O`).
3.  Select the following two files from the Docs folder:
    *   `campusflow_postman_collection.json`
    *   `campusflow_postman_environment.json`
4.  Confirm the import and ensure they are loaded.

---

## Step 2 — Activate the Environment

1.  In the top right dropdown of Postman, select the environment named **CampusFlow Environment**.
2.  Review the predefined variables. The `base_url` is pre-configured to `http://localhost:8000`. You can change it to point to your development/staging server.

---

## Step 3 — Walkthrough: Authentication & Token Reuse

The collection is pre-configured with **Inherited Authentication** (`Bearer Token`).

1.  Navigate to the folder **Authentication**.
2.  Run the **Request OTP** endpoint to register an email.
3.  Run the **Verify Account** endpoint with your email and the OTP to activate the user.
4.  Select the **Login** request.
5.  Send the request. The collection's **Tests** tab contains a post-response script:
    ```javascript
    var jsonData = pm.response.json();
    if (jsonData.access) {
        pm.environment.set("access_token", jsonData.access);
    }
    if (jsonData.refresh) {
        pm.environment.set("refresh_token", jsonData.refresh);
    }
    if (jsonData.tenant_schema) {
        pm.environment.set("tenant_slug", jsonData.tenant_schema);
    }
    if (jsonData.user_id) {
        pm.environment.set("user_id", jsonData.user_id);
    }
    ```
6.  Once executed, the environment variables (`access_token`, `refresh_token`, and `tenant_slug`) will be automatically populated. All other requests in the collection (such as **Departments**, **Attendance**, and **Salary**) will automatically inherit and include these tokens.

---

## Step 4 — Multi-Tenancy (Headers)

All tenant-scoped requests automatically include:
*   `X-Tenant`: `{{tenant_slug}}` in the headers.
*   This matches the dynamic schema resolution configured in `CampusFlowTenantMiddleware`.
