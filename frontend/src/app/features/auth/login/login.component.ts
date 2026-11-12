import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { AuthService } from '../../../core/services/auth.service';
import { ParticleBackgroundComponent } from '../../../shared/components/particle-background/particle-background.component';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, MatSnackBarModule, RouterModule, ParticleBackgroundComponent],
  templateUrl: './login.component.html',
  styleUrls: ['./login.component.scss'],
})
export class LoginComponent implements OnInit {
  form: FormGroup;
  loading = signal(false);
  showPassword = signal(false);
  allowRegistration = signal(false);

  constructor(
    private fb: FormBuilder,
    private auth: AuthService,
    private router: Router,
    private snackBar: MatSnackBar,
  ) {
    this.form = this.fb.group({
      email: ['', [Validators.required, Validators.email]],
      password: ['', Validators.required],
    });
  }

  ngOnInit(): void {
    // Sem resposta do servidor, o link de cadastro continua oculto.
    this.auth.getConfig().subscribe({
      next: config => this.allowRegistration.set(config.allow_registration),
    });
  }

  submit(): void {
    if (this.form.invalid || this.loading()) return;
    this.loading.set(true);

    this.auth.login(this.form.value).subscribe({
      next: () => {
        this.router.navigate(['/dashboard']);
      },
      error: (err: unknown) => {
        this.loading.set(false);
        const msg = err instanceof Error ? err.message : 'Falha no login';
        this.snackBar.open(msg, 'Fechar', {
          duration: 4000,
          panelClass: ['snack-error'],
        });
      },
    });
  }
}
