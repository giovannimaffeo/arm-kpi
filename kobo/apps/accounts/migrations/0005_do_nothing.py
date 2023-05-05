# Generated by Django 3.2.15 on 2023-04-07 23:40

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('socialaccount', '0003_extra_data_default_dict'),
        ('accounts', '0004_socialappcustomdata'),
    ]

    operations = [
        migrations.AlterField(
            model_name='emailcontent',
            name='content',
            field=models.TextField(blank=True, help_text='Available placeholders:<br/> ##activate_url## - The activation URL to activate new accounts<br/>##user## - The username of the user,'),
        ),
        migrations.AlterField(
            model_name='emailcontent',
            name='email_name',
            field=models.CharField(choices=[('email_confirmation_signup_message', 'Email Confirmation Signup Message')], default=None, max_length=120),
        ),
        migrations.AlterField(
            model_name='emailcontent',
            name='section_name',
            field=models.CharField(choices=[('subject', 'Subject'), ('section_one', 'Section One'), ('section_two', 'Section Two')], default=None, max_length=120),
        ),
        migrations.AlterField(
            model_name='socialappcustomdata',
            name='social_app',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, related_name='custom_data', serialize=False, to='socialaccount.socialapp'),
        ),
    ]
