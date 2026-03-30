from django.shortcuts import render, redirect
from django.contrib import messages
from django.core.mail import send_mail
from django.conf import settings
from .models import ContactProfile, ContactSetting, ContactMessage
from .forms import ContactForm


def contact_page(request):
    """
    Main contact page view
    """
    contact_profiles = ContactProfile.objects.filter(is_active=True)
    contact_settings = ContactSetting.objects.first()

    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            # Save message to database
            contact_message = form.save(commit=False)
            contact_message.ip_address = get_client_ip(request)
            contact_message.user_agent = request.META.get('HTTP_USER_AGENT', '')
            contact_message.save()

            # Send email notification
            if contact_settings:
                send_mail(
                    f"New Contact Message: {form.cleaned_data['subject']}",
                    f"""
                    Name: {form.cleaned_data['name']}
                    Email: {form.cleaned_data['email']}
                    Message: {form.cleaned_data['message']}

                    IP: {contact_message.ip_address}
                    """,
                    settings.DEFAULT_FROM_EMAIL,
                    [contact_settings.contact_email],
                    fail_silently=False,
                )

            messages.success(request, 'Thank you for your message! I will get back to you soon.')
            return redirect('contact:contact_page')
    else:
        form = ContactForm()

    context = {
        'contact_profiles': contact_profiles,
        'contact_settings': contact_settings,
        'form': form,
    }

    return render(request, 'contact/contact_page.html', context)


def get_client_ip(request):
    """Get client IP address"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip
