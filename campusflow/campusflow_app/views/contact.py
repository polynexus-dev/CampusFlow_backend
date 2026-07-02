from django.core.mail import EmailMessage
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.conf import settings

class ContactEnquiryView(APIView):
    permission_classes = [AllowAny]  # Anyone can submit this from the landing page

    def post(self, request, *args, **kwargs):
        try:
            data = request.data
            full_name = data.get('fullName')
            designation = data.get('designation')
            institution_name = data.get('institutionName')
            email = data.get('email')
            phone = data.get('phone', 'N/A')
            size = data.get('institutionSize')
            message = data.get('message', 'N/A')

            # Validate mandatory fields
            if not all([full_name, designation, institution_name, email, size]):
                return Response(
                    {'error': 'Missing required fields (fullName, designation, institutionName, email, institutionSize).'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Format the notification email body
            subject = f"New CampusNexus Demo Request - {institution_name}"
            email_body = f"""
New enquiry received from the CampusNexus landing page:

- Name: {full_name}
- Designation: {designation}
- Institution: {institution_name}
- Email: {email}
- Phone: {phone}
- Student Strength: {size}

Message:
{message}
"""

            # Send mail using EmailMessage for To, CC, and BCC support
            email_msg = EmailMessage(
                subject=subject,
                body=email_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[settings.CONTACT_RECIPIENT_EMAIL],
                cc=settings.CONTACT_CC_LIST,
                bcc=settings.CONTACT_BCC_LIST,
            )
            email_msg.send(fail_silently=False)

            return Response({'message': 'Enquiry received successfully.'}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
