import pymysql
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'clave_secreta_para_sesion'

def get_db_connection():
    return pymysql.connect(
        host='localhost',
        user='root',
        password='',
        database='web_asesorias',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )

# Ruta principal (página de inicio con "Sobre Nosotros")
@app.route('/')
def index():
    return render_template('index.html')

# Ruta de bienvenida que redirige según rol
@app.route('/inicio')
def dashboard():
    if 'user_id' in session:
        if session['rol'] == 'alumno':
            return redirect(url_for('alumno'))
        elif session['rol'] == 'maestro':
            return redirect(url_for('maestro'))
    return redirect(url_for('login'))

# Registro de usuarios
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        nombre = request.form['nombre']
        email = request.form['email']
        password = request.form['password']
        rol = request.form['rol']
        terminos = request.form.get('terminos')

        if not all([nombre, email, password, rol]):
            flash('Completa todos los campos.', 'error')
            return redirect(url_for('register'))

        if rol not in ['alumno', 'maestro']:
            flash('Rol no válido.', 'error')
            return redirect(url_for('register'))

        if not terminos:
            flash('Debes aceptar los Términos y Condiciones.', 'error')
            return redirect(url_for('register'))

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT id FROM usuarios WHERE email = %s', (email,))
                if cur.fetchone():
                    flash('El correo ya está registrado.', 'error')
                    return redirect(url_for('register'))

                hashed = generate_password_hash(password)
                cur.execute(
                    'INSERT INTO usuarios (nombre, email, password, rol) VALUES (%s, %s, %s, %s)',
                    (nombre, email, hashed, rol)
                )
                user_id = cur.lastrowid  # ← Obtén el ID del nuevo usuario

                # Enviar notificación de bienvenida
                rol_texto = "Alumno" if rol == 'alumno' else "Profesor"
                enviar_notificacion(
                    usuario_id=user_id,
                    titulo="¡Bienvenido a Web Asesorías!",
                    mensaje=f"¡Hola {nombre}! Tu cuenta como {rol_texto} ha sido creada exitosamente. ¡Comienza a explorar!"
                )

        finally:
            conn.close()

        flash('Registro exitoso. Ahora inicia sesión.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

# Iniciar sesión
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT * FROM usuarios WHERE email = %s', (email,))
                user = cur.fetchone()
        finally:
            conn.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['nombre'] = user['nombre']
            session['rol'] = user['rol']

            # Redirigir según rol
            if user['rol'] == 'alumno':
                return redirect(url_for('alumno'))
            elif user['rol'] == 'maestro':
                return redirect(url_for('maestro'))
        else:
            flash('Credenciales incorrectas.', 'error')

    return render_template('login.html')

# Panel del alumno
@app.route('/alumno')
def alumno():
    if 'user_id' not in session or session['rol'] != 'alumno':
        flash('Acceso no autorizado.', 'error')
        return redirect(url_for('login'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # ========== Datos para "Mis Temas" y "Calificaciones" ==========
            cur.execute("""
                SELECT 
                    t.nombre AS tema,
                    u.nombre AS asesor,
                    u.id AS asesor_id,
                    COALESCE(c.nota, 'N/A') AS calificacion,
                    CASE 
                        WHEN c.nota IS NOT NULL THEN 'Aprobado'
                        ELSE 'Pendiente'
                    END AS estado
                FROM alumno_tema at
                JOIN temas t ON at.tema_id = t.id
                JOIN usuarios u ON t.maestro_id = u.id
                LEFT JOIN calificaciones c ON c.alumno_id = %s AND c.tema_id = t.id
                WHERE at.alumno_id = %s
                ORDER BY t.nombre
            """, (session['user_id'], session['user_id']))
            mis_asesorias = cur.fetchall()

            cur.execute("""
                SELECT 
                    t.nombre AS tema,
                    u.nombre AS asesor,
                    COALESCE(c.nota, 'N/A') AS calificacion,
                    c.fecha
                FROM calificaciones c
                JOIN temas t ON c.tema_id = t.id
                JOIN usuarios u ON t.maestro_id = u.id
                WHERE c.alumno_id = %s
                ORDER BY c.fecha DESC
            """, (session['user_id'],))
            mis_calificaciones = cur.fetchall()

            # ========== Datos para "Buscar Temas" ==========
            cur.execute("""
                SELECT t.id, t.nombre, t.descripcion, t.hora, t.aula, u.nombre AS maestro_nombre
                FROM temas t
                JOIN usuarios u ON t.maestro_id = u.id
                WHERE t.activo = TRUE
                AND t.id NOT IN (
                    SELECT tema_id FROM alumno_tema WHERE alumno_id = %s
                )
            """, (session['user_id'],))
            temas_disponibles = cur.fetchall()

            cur.execute("SELECT tema_id FROM alumno_tema WHERE alumno_id = %s", (session['user_id'],))
            inscrito_ids = [row['tema_id'] for row in cur.fetchall()]

            # ========== Datos para "Notificaciones" ==========
            cur.execute("""
                SELECT * FROM notificaciones 
                WHERE usuario_id = %s
                ORDER BY created_at DESC
            """, (session['user_id'],))
            notificaciones = cur.fetchall()

            # ========== Estadísticas ==========
            cur.execute("SELECT COUNT(*) FROM alumno_tema WHERE alumno_id = %s", (session['user_id'],))
            temas_inscritos = cur.fetchone()['COUNT(*)']

            cur.execute("SELECT COUNT(*) FROM calificaciones WHERE alumno_id = %s", (session['user_id'],))
            calificaciones = cur.fetchone()['COUNT(*)']

            cur.execute("""
                SELECT COUNT(*)
                FROM alumno_tema at
                JOIN temas t ON at.tema_id = t.id
                LEFT JOIN calificaciones c ON c.alumno_id = at.alumno_id AND c.tema_id = t.id
                WHERE at.alumno_id = %s AND c.nota IS NULL
            """, (session['user_id'],))
            pendientes = cur.fetchone()['COUNT(*)']

            stats = {
                'temas_inscritos': temas_inscritos,
                'calificaciones': calificaciones,
                'pendientes': pendientes
            }
    finally:
        conn.close()

    return render_template('alumno.html', 
                         nombre=session['nombre'], 
                         mis_asesorias=mis_asesorias, 
                         mis_calificaciones=mis_calificaciones,
                         temas_disponibles=temas_disponibles,
                         inscrito_ids=inscrito_ids,
                         notificaciones=notificaciones,
                         stats=stats)

# Panel del maestro
@app.route('/maestro')
def maestro():
    if 'user_id' not in session or session['rol'] != 'maestro':
        flash('Acceso no autorizado.', 'error')
        return redirect(url_for('login'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Estadísticas
            cur.execute("SELECT COUNT(DISTINCT alumno_id) FROM alumno_tema at JOIN temas t ON at.tema_id = t.id WHERE t.maestro_id = %s", (session['user_id'],))
            alumnos_count = cur.fetchone()['COUNT(DISTINCT alumno_id)']

            cur.execute("SELECT COUNT(*) FROM temas WHERE maestro_id = %s", (session['user_id'],))
            temas_count = cur.fetchone()['COUNT(*)']

            cur.execute("SELECT COUNT(*) FROM notificaciones WHERE usuario_id = %s AND leida = FALSE", (session['user_id'],))
            notificaciones_pendientes = cur.fetchone()['COUNT(*)']

            # ✅ Alumnos inscritos en los temas del maestro (CORREGIDO)
            cur.execute("""
                SELECT DISTINCT
                u.id,
                u.nombre,
                u.email
                FROM usuarios u 
                INNER JOIN alumno_tema at ON u.id = at.alumno_id 
                INNER JOIN temas t ON at.tema_id = t.id 
                WHERE t.maestro_id = %s 
                AND u.rol = 'alumno'
            """, (session['user_id'],))
            alumnos = cur.fetchall()

            # ✅ Temas creados por el maestro
            cur.execute("""
                SELECT * FROM temas 
                WHERE maestro_id = %s 
                ORDER BY created_at DESC
            """, (session['user_id'],))
            temas = cur.fetchall()

            # ✅ Calificaciones
            cur.execute("""
                SELECT 
                    u.nombre AS alumno_nombre,
                    t.nombre AS tema_nombre,
                    COALESCE(c.nota, 'N/A') AS nota,
                    c.fecha,
                    u.id AS alumno_id,
                    t.id AS tema_id
                FROM usuarios u
                INNER JOIN alumno_tema at ON u.id = at.alumno_id
                INNER JOIN temas t ON at.tema_id
                LEFT JOIN calificaciones c ON c.alumno_id = u.id AND c.tema_id = t.id
                WHERE t.maestro_id = %s
                AND u.rol = 'alumno'
                ORDER BY u.nombre, t.nombre
            """, (session['user_id'],))
            calificaciones = cur.fetchall()

            # ✅ Notificaciones
            cur.execute("""
                SELECT * FROM notificaciones 
                WHERE usuario_id = %s
                ORDER BY created_at DESC
            """, (session['user_id'],))
            notificaciones = cur.fetchall()

            stats = {
                'alumnos': alumnos_count,
                'temas': temas_count,
                'notificaciones_pendientes': notificaciones_pendientes
            }
    finally:
        conn.close()

    return render_template('maestro.html', 
                         nombre=session['nombre'], 
                         stats=stats,
                         alumnos=alumnos,
                         temas=temas,
                         calificaciones=calificaciones,
                         notificaciones=notificaciones)

# Editar calificación
@app.route('/maestro/calificacion/<int:alumno_id>/<int:tema_id>', methods=['GET', 'POST'])
def editar_calificacion(alumno_id, tema_id):
    if 'user_id' not in session or session['rol'] != 'maestro':
        flash('Acceso no autorizado.', 'error')
        return redirect(url_for('login'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if request.method == 'POST':
                nota = request.form.get('nota')
                if nota and 0 <= float(nota) <= 100:
                    cur.execute("""
                        INSERT INTO calificaciones (alumno_id, tema_id, nota)
                        VALUES (%s, %s, %s)
                        ON DUPLICATE KEY UPDATE nota = %s
                    """, (alumno_id, tema_id, nota, nota))
                    conn.commit()
                    flash('Calificación actualizada.', 'success')
                else:
                    flash('La nota debe estar entre 0 y 100.', 'error')

            cur.execute("SELECT nombre FROM usuarios WHERE id = %s", (alumno_id,))
            alumno = cur.fetchone()
            cur.execute("SELECT nombre FROM temas WHERE id = %s", (tema_id,))
            tema = cur.fetchone()
    finally:
        conn.close()

    return render_template('editar_calificacion.html', 
                           nombre=session['nombre'], 
                           alumno=alumno, 
                           tema=tema, 
                           alumno_id=alumno_id, 
                           tema_id=tema_id)


# Crear tema
@app.route('/maestro/temas/crear', methods=['GET', 'POST'])
def crear_tema():
    if 'user_id' not in session or session['rol'] != 'maestro':
        flash('Acceso no autorizado.', 'error')
        return redirect(url_for('login'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM usuarios WHERE id = %s", (session['user_id'],))
            if not cur.fetchone():
                session.clear()
                flash('Sesión inválida. Por favor, inicia sesión de nuevo.', 'error')
                return redirect(url_for('login'))
    finally:
        conn.close()

    if request.method == 'POST':
        nombre = request.form['nombre']
        descripcion = request.form.get('descripcion', '')
        hora = request.form['hora']
        aula = request.form['aula']

        if not nombre or not hora or not aula:
            flash('Nombre, hora y aula son obligatorios.', 'error')
            return redirect(url_for('crear_tema'))

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO temas (nombre, descripcion, maestro_id, hora, aula)
                    VALUES (%s, %s, %s, %s, %s)
                """, (nombre, descripcion, session['user_id'], hora, aula))
            conn.commit()
        finally:
            conn.close()

        flash('Tema creado exitosamente.', 'success')
        return redirect(url_for('maestro'))

    return render_template('crear_tema.html', nombre=session['nombre'])

# Aceptar un tema
@app.route('/alumno/tema/<int:tema_id>/aceptar', methods=['POST'])
def aceptar_tema(tema_id):
    if 'user_id' not in session or session['rol'] != 'alumno':
        flash('Acceso no autorizado.', 'error')
        return redirect(url_for('login'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT maestro_id FROM temas WHERE id = %s AND activo = TRUE", (tema_id,))
            tema = cur.fetchone()
            if not tema:
                flash('Tema no válido.', 'error')
                return redirect(url_for('alumno'))

            cur.execute("""
                INSERT INTO alumno_tema (alumno_id, tema_id)
                VALUES (%s, %s)
            """, (session['user_id'], tema_id))

            cur.execute("""
                INSERT INTO notificaciones (usuario_id, titulo, mensaje)
                VALUES (%s, %s, %s)
            """, (
                tema['maestro_id'],
                'Nuevo alumno en tu tema',
                f'El alumno {session["nombre"]} ha aceptado el tema "{tema_id}".'
            ))
        conn.commit()
    finally:
        conn.close()

    flash('Tema aceptado exitosamente.', 'success')
    return redirect(url_for('alumno'))

# Reportar usuario
@app.route('/reportar/<int:user_id_reportado>')
def reportar(user_id_reportado):
    if 'user_id' not in session:
        flash('Debes iniciar sesión para reportar a un usuario.', 'error')
        return redirect(url_for('login'))

    if session['user_id'] == user_id_reportado:
        flash('No puedes reportarte a ti mismo.', 'warning')
        return redirect(url_for('alumno'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT nombre FROM usuarios WHERE id = %s", (user_id_reportado,))
            usuario = cur.fetchone()
            if not usuario:
                flash('El usuario que intentas reportar no existe.', 'error')
                return redirect(url_for('alumno'))
    finally:
        conn.close()

    return render_template('reportar.html', user_id_reportado=user_id_reportado)

# Enviar reporte
@app.route('/enviar-reporte', methods=['POST'])
def enviar_reporte():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id_reportado = request.form.get('user_id_reportado')
    razon = request.form.get('razon')
    comentarios = request.form.get('comentarios')

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO reportes (reportado_por, usuario_reportado, razon, comentarios)
                VALUES (%s, %s, %s, %s)
            """, (session['user_id'], user_id_reportado, razon, comentarios))
        conn.commit()
    finally:
        conn.close()

    flash('Tu reporte ha sido enviado al administrador. Gracias.', 'success')
    return redirect(url_for('alumno'))

# Cerrar sesión
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/admin/secret-login', methods=['GET', 'POST'])
def admin_secret_login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == 'admin123':  # 🔐 Cambia esto por una contraseña más segura
            session['is_admin'] = True
            flash('Acceso de administrador concedido.', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Contraseña incorrecta.', 'error')

    return render_template('admin_secret_login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('is_admin'):
        flash('Acceso no autorizado.', 'error')
        return redirect(url_for('index'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Obtener todos los usuarios
            cur.execute("SELECT id, nombre, email, rol, created_at FROM usuarios ORDER BY rol, nombre")
            usuarios = cur.fetchall()

            # Obtener reportes pendientes
            cur.execute("""
                SELECT r.id, u1.nombre AS reportado_por, u2.nombre AS usuario_reportado, 
                       r.razon, r.comentarios, r.estado, r.fecha
                FROM reportes r
                JOIN usuarios u1 ON r.reportado_por = u1.id
                JOIN usuarios u2 ON r.usuario_reportado = u2.id
                ORDER BY r.fecha DESC
            """)
            reportes = cur.fetchall()

    finally:
        conn.close()

    return render_template('admin_dashboard.html', usuarios=usuarios, reportes=reportes)

@app.route('/admin/toggle-role/<int:user_id>/<string:target_role>')
def toggle_role(user_id, target_role):
    if not session.get('is_admin'):
        flash('Acceso no autorizado.', 'error')
        return redirect(url_for('index'))

    if target_role not in ['alumno', 'maestro']:
        flash('Rol inválido.', 'error')
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE usuarios SET rol = %s WHERE id = %s", (target_role, user_id))
            conn.commit()
        flash(f'Rol actualizado a {target_role}.', 'success')
    finally:
        conn.close()

    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete-user/<int:user_id>')
def delete_user(user_id):
    if not session.get('is_admin'):
        flash('Acceso no autorizado.', 'error')
        return redirect(url_for('index'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM usuarios WHERE id = %s", (user_id,))
            conn.commit()
        flash('Usuario eliminado.', 'success')
    finally:
        conn.close()

    return redirect(url_for('admin_dashboard'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    flash('Sesión de administrador cerrada.', 'info')
    return redirect(url_for('index'))

@app.route('/admin/sancionar/<int:user_id>', methods=['POST'])
def sancionar_usuario(user_id):
    if not session.get('is_admin'):
        flash('Acceso no autorizado.', 'error')
        return redirect(url_for('index'))

    motivo = request.form.get('motivo', 'Conducta inapropiada')
    enviar_notificacion(
        usuario_id=user_id,
        titulo='⚠️ Notificación de Infracción',
        mensaje=f'Se te ha aplicado una sanción por: {motivo}. Por favor revisa nuestras políticas.'
    )
    flash('Notificación de infracción enviada.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/perfil')
def perfil():
    if 'user_id' not in session:
        flash('Debes iniciar sesión para ver esta página.', 'error')
        return redirect(url_for('login'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT nombre, email, rol FROM usuarios WHERE id = %s", (session['user_id'],))
            user = cur.fetchone()
            if not user:
                session.clear()
                flash('Sesión inválida.', 'error')
                return redirect(url_for('login'))
    finally:
        conn.close()

    return render_template('perfil.html', user=user)

def enviar_notificacion(usuario_id, titulo, mensaje):
    """Envía una notificación a cualquier usuario (alumno o maestro)."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO notificaciones (usuario_id, titulo, mensaje)
                VALUES (%s, %s, %s)
            """, (usuario_id, titulo, mensaje))
        conn.commit()
    finally:
        conn.close()

if __name__ == '__main__':
    app.run(debug=True, port=5000)