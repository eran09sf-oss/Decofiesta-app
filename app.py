from functools import wraps
import sys
from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_mysqldb import MySQL

app = Flask(__name__)

# Configuración de sesión y mensajes flash
app.config["SECRET_KEY"] = "mi_clave_secreta_super_segura"

# --- Configuración de la base de datos ---
app.config["MYSQL_HOST"] = "localhost"
app.config["MYSQL_USER"] = "root"
app.config["MYSQL_PASSWORD"] = "root"
app.config["MYSQL_DB"] = "tiendita"
app.config["MYSQL_CURSORCLASS"] = "DictCursor"

mysql = MySQL(app)


# ----------------- Decorador de Autenticación -----------------


def login_required(f):
    """Verifica si el usuario ha iniciado sesión; si no, redirige a /login."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            flash("Por favor, inicia sesión para acceder a esta página.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


# ----------------- Funciones Auxiliares -----------------


def convert_unitario_to_float(registros):
    """Convierte campos numéricos de compras y ventas a float/int para Jinja."""
    if isinstance(registros, dict):
        lista = [registros]
    elif isinstance(registros, list):
        lista = registros
    else:
        return registros

    float_fields = ("unitario", "monto", "precio_unitario", "total")
    int_fields = ("stock", "cantidad")

    for item in lista:
        for campo in float_fields:
            if campo in item:
                try:
                    item[campo] = float(item[campo])
                except (TypeError, ValueError):
                    item[campo] = 0.0

        for campo in int_fields:
            if campo in item:
                try:
                    item[campo] = int(item[campo])
                except (TypeError, ValueError):
                    item[campo] = 0

    return lista[0] if isinstance(registros, dict) else lista


def verify_and_update_db_schema():
    """Asegura que las tablas compras y ventas existan con la estructura esperada."""
    cursor = None
    try:
        cursor = mysql.connection.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS compras (
                id_compra INT PRIMARY KEY,
                nombre VARCHAR(255) NOT NULL,
                marca VARCHAR(255),
                modelo VARCHAR(255),
                presentacion VARCHAR(255),
                proveedor VARCHAR(255),
                unitario DECIMAL(10,2) NOT NULL,
                stock INT NOT NULL DEFAULT 0
            )
            """
        )

        cursor.execute("SHOW COLUMNS FROM compras LIKE 'stock'")
        if not cursor.fetchone():
            cursor.execute(
                "ALTER TABLE compras ADD COLUMN stock INT NOT NULL DEFAULT 0"
            )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ventas (
                id_venta INT AUTO_INCREMENT PRIMARY KEY,
                cliente_dni VARCHAR(255) NOT NULL,
                producto_ref VARCHAR(255) NOT NULL,
                cantidad INT NOT NULL DEFAULT 1,
                monto DECIMAL(10,2) NOT NULL,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute("SHOW COLUMNS FROM ventas LIKE 'cliente_dni'")
        if not cursor.fetchone():
            cursor.execute("DROP TABLE IF EXISTS ventas")
            cursor.execute(
                """
                CREATE TABLE ventas (
                    id_venta INT AUTO_INCREMENT PRIMARY KEY,
                    cliente_dni VARCHAR(255) NOT NULL,
                    producto_ref VARCHAR(255) NOT NULL,
                    cantidad INT NOT NULL DEFAULT 1,
                    monto DECIMAL(10,2) NOT NULL,
                    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

        mysql.connection.commit()
    except Exception as e:
        print(f"Aviso durante la verificación de esquema DB: {e}", file=sys.stderr)
    finally:
        if cursor:
            cursor.close()


def get_compra(compra_id):
    """Obtiene un registro de compra por su ID con su stock."""
    cursor = None
    try:
        cursor = mysql.connection.cursor()
        cursor.execute(
            """
            SELECT id_compra, nombre, marca, modelo, presentacion, proveedor, unitario, stock
            FROM compras
            WHERE id_compra = %s
            """,
            (compra_id,),
        )
        compra = cursor.fetchone()
        return convert_unitario_to_float(compra) if compra else None
    finally:
        if cursor:
            cursor.close()


def get_ventas_list():
    """Obtiene la lista de ventas registradas con datos formateados."""
    cursor = None
    try:
        cursor = mysql.connection.cursor()
        cursor.execute(
            """
            SELECT id_venta, cliente_dni, producto_ref, cantidad, monto, fecha
            FROM ventas
            ORDER BY id_venta DESC
            """
        )
        ventas = cursor.fetchall()
        return convert_unitario_to_float(ventas)
    except Exception as e:
        print(f"Error al obtener ventas: {e}", file=sys.stderr)
        return []
    finally:
        if cursor:
            cursor.close()


# ----------------- Rutas de Autenticación -----------------


@app.route("/login", methods=["GET", "POST"])
def login():
    """Maneja el inicio de sesión del usuario."""
    if request.method == "POST":
        valid_username = "admin"
        valid_password = "password"

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if username == valid_username and password == valid_password:
            session["logged_in"] = True
            session["username"] = username
            flash("¡Sesión iniciada correctamente!", "success")
            return redirect(url_for("index"))

        flash("Credenciales inválidas. Inténtalo de nuevo.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    """Cierra la sesión del usuario."""
    session.pop("logged_in", None)
    session.pop("username", None)
    flash("Has cerrado sesión exitosamente.", "info")
    return redirect(url_for("login"))


# ----------------- Rutas de Gestión de Compras / Inventario -----------------


@app.route("/")
@login_required
def index():
    """Muestra la lista de compras/inventario y ventas registradas."""
    cursor = None
    try:
        cursor = mysql.connection.cursor()
        cursor.execute(
            """
            SELECT id_compra, nombre, marca, modelo, presentacion, proveedor, unitario, stock
            FROM compras
            ORDER BY id_compra DESC
            """
        )
        compras = convert_unitario_to_float(cursor.fetchall())
        ventas = get_ventas_list()

        return render_template(
            "index.html",
            compras=compras,
            ventas=ventas,
            search_query=None,
            compra_a_editar=None,
        )
    except Exception as e:
        print(f"Error al conectar/consultar la base de datos: {e}", file=sys.stderr)
        return render_template(
            "index.html",
            error_msg=f"Error de conexión a la base de datos. Detalles: {e}",
            compras=[],
            ventas=[],
            compra_a_editar=None,
        )
    finally:
        if cursor:
            cursor.close()


@app.route("/add", methods=["POST"])
@login_required
def add():
    """Inserta un nuevo producto/compra con stock inicial."""
    cursor = None
    try:
        id_compra = int(request.form["id_compra"])
        nombre = request.form["nombre"].strip()
        marca = request.form.get("marca", "").strip()
        modelo = request.form.get("modelo", "").strip()
        presentacion = request.form.get("presentacion", "").strip()
        proveedor = request.form.get("proveedor", "").strip()
        unitario = float(request.form["unitario"])
        stock = int(request.form.get("stock", 0))

        if not nombre:
            flash("El nombre del producto es obligatorio.", "error")
            return redirect(url_for("index"))

        if unitario < 0 or stock < 0:
            flash("El costo unitario y el stock no pueden ser negativos.", "error")
            return redirect(url_for("index"))

        cursor = mysql.connection.cursor()
        query = """
            INSERT INTO compras (id_compra, nombre, marca, modelo, presentacion, proveedor, unitario, stock)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(
            query, (id_compra, nombre, marca, modelo, presentacion, proveedor, unitario, stock)
        )
        mysql.connection.commit()

        flash("Producto/Compra agregado exitosamente con stock.", "success")
        return redirect(url_for("index"))

    except ValueError:
        flash("Error: El ID, costo unitario y stock deben ser números válidos.", "error")
        return redirect(url_for("index"))
    except Exception as e:
        mysql.connection.rollback()
        print(f"Error al procesar la compra: {e}", file=sys.stderr)
        flash(f"Error al agregar compra: {e}", "error")
        return redirect(url_for("index"))
    finally:
        if cursor:
            cursor.close()


@app.route("/edit/<int:compra_id>")
@login_required
def edit(compra_id):
    """Carga los datos de una compra específica para el formulario de edición."""
    compra_a_editar = get_compra(compra_id)
    if not compra_a_editar:
        flash("Registro de compra no encontrado.", "error")
        return redirect(url_for("index"))

    cursor = None
    try:
        cursor = mysql.connection.cursor()
        cursor.execute(
            """
            SELECT id_compra, nombre, marca, modelo, presentacion, proveedor, unitario, stock
            FROM compras
            ORDER BY id_compra DESC
            """
        )
        compras = convert_unitario_to_float(cursor.fetchall())
    except Exception as e:
        print(f"Error al obtener listado de compras en edición: {e}", file=sys.stderr)
        compras = []
    finally:
        if cursor:
            cursor.close()

    ventas = get_ventas_list()
    return render_template(
        "index.html",
        compras=compras,
        ventas=ventas,
        search_query=None,
        compra_a_editar=compra_a_editar,
    )


@app.route("/update/<int:compra_id>", methods=["POST"])
@login_required
def update(compra_id):
    """Actualiza un registro de compra e inventario existente."""
    cursor = None
    try:
        nuevo_id_compra = int(request.form["id_compra"])
        nombre = request.form["nombre"].strip()
        marca = request.form.get("marca", "").strip()
        modelo = request.form.get("modelo", "").strip()
        presentacion = request.form.get("presentacion", "").strip()
        proveedor = request.form.get("proveedor", "").strip()
        unitario = float(request.form["unitario"])
        stock = int(request.form.get("stock", 0))

        if not nombre:
            flash("El nombre del producto es obligatorio.", "error")
            return redirect(url_for("edit", compra_id=compra_id))

        if unitario < 0 or stock < 0:
            flash("El costo unitario y el stock no pueden ser negativos.", "error")
            return redirect(url_for("edit", compra_id=compra_id))

        cursor = mysql.connection.cursor()
        query = """
            UPDATE compras SET
                id_compra = %s,
                nombre = %s,
                marca = %s,
                modelo = %s,
                presentacion = %s,
                proveedor = %s,
                unitario = %s,
                stock = %s
            WHERE id_compra = %s
        """
        cursor.execute(
            query,
            (
                nuevo_id_compra,
                nombre,
                marca,
                modelo,
                presentacion,
                proveedor,
                unitario,
                stock,
                compra_id,
            ),
        )
        mysql.connection.commit()

        flash("Registro actualizado exitosamente.", "success")
        return redirect(url_for("index"))

    except ValueError:
        flash("Error: Verifica que ID, costo unitario y stock sean valores válidos.", "error")
        return redirect(url_for("edit", compra_id=compra_id))
    except Exception as e:
        mysql.connection.rollback()
        print(f"Error al actualizar la compra: {e}", file=sys.stderr)
        flash(f"Error al actualizar compra: {e}", "error")
        return redirect(url_for("edit", compra_id=compra_id))
    finally:
        if cursor:
            cursor.close()


@app.route("/delete/<int:compra_id>", methods=["POST"])
@login_required
def delete(compra_id):
    """Elimina una compra de la base de datos."""
    cursor = None
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("DELETE FROM compras WHERE id_compra = %s", (compra_id,))
        mysql.connection.commit()
        flash(f"Compra ID {compra_id} eliminada exitosamente.", "info")
    except Exception as e:
        mysql.connection.rollback()
        print(f"Error al eliminar la compra: {e}", file=sys.stderr)
        flash(f"Error al eliminar la compra ID {compra_id}: {e}", "error")
    finally:
        if cursor:
            cursor.close()

    return redirect(url_for("index"))


@app.route("/search", methods=["GET"])
@login_required
def search():
    """Busca compras por ID."""
    search_query = request.args.get("id_compra", "").strip()
    if not search_query:
        return redirect(url_for("index"))

    cursor = None
    try:
        id_buscado = int(search_query)
        cursor = mysql.connection.cursor()
        cursor.execute(
            """
            SELECT id_compra, nombre, marca, modelo, presentacion, proveedor, unitario, stock
            FROM compras
            WHERE id_compra = %s
            """,
            (id_buscado,),
        )
        results = convert_unitario_to_float(cursor.fetchall())
        ventas = get_ventas_list()

        if results:
            flash(f'Se encontró {len(results)} compra(s) con ID "{id_buscado}".', "info")
        else:
            flash(f'No se encontraron compras con ID "{id_buscado}".', "warning")

        return render_template(
            "index.html",
            compras=results,
            ventas=ventas,
            search_query=search_query,
            compra_a_editar=None,
        )
    except ValueError:
        flash("Ingresa un ID numérico válido para buscar.", "error")
        return redirect(url_for("index"))
    except Exception as e:
        print(f"Error en la búsqueda de la base de datos: {e}", file=sys.stderr)
        flash("Error al realizar la búsqueda en la base de datos.", "error")
        return redirect(url_for("index"))
    finally:
        if cursor:
            cursor.close()


# ----------------- Ruta de Ventas con Afectación al Stock -----------------


@app.route("/add_sale", methods=["POST"])
@login_required
def add_sale():
    """Registra una venta y descuenta stock si producto_ref coincide con id_compra o nombre."""
    cursor = None
    try:
        cliente_dni = request.form["cliente_dni"].strip()
        producto_ref = request.form["producto_ref"].strip()
        cantidad = int(request.form.get("cantidad", 1))
        monto = float(request.form["monto"])

        if not cliente_dni or not producto_ref:
            flash("Completa el cliente/DNI y la referencia del producto.", "error")
            return redirect(url_for("index"))

        if cantidad <= 0:
            flash("La cantidad a vender debe ser mayor a 0.", "error")
            return redirect(url_for("index"))

        if monto < 0:
            flash("El monto de la venta no puede ser negativo.", "error")
            return redirect(url_for("index"))

        cursor = mysql.connection.cursor()

        if producto_ref.isdigit():
            cursor.execute(
                "SELECT id_compra, stock FROM compras WHERE id_compra = %s OR nombre = %s",
                (int(producto_ref), producto_ref),
            )
        else:
            cursor.execute(
                "SELECT id_compra, stock FROM compras WHERE nombre = %s",
                (producto_ref,),
            )

        producto = cursor.fetchone()

        if producto:
            stock_actual = int(producto["stock"])
            id_compra_encontrado = producto["id_compra"]

            if stock_actual < cantidad:
                flash(
                    f'Stock insuficiente para "{producto_ref}". Disponible: {stock_actual}, Solicitado: {cantidad}.',
                    "error",
                )
                return redirect(url_for("index"))

            actualizado = cursor.execute(
                """
                UPDATE compras
                SET stock = stock - %s
                WHERE id_compra = %s AND stock >= %s
                """,
                (cantidad, id_compra_encontrado, cantidad),
            )
            if actualizado == 0:
                mysql.connection.rollback()
                flash("No se pudo descontar el stock; inténtalo de nuevo.", "error")
                return redirect(url_for("index"))

        cursor.execute(
            """
            INSERT INTO ventas (cliente_dni, producto_ref, cantidad, monto)
            VALUES (%s, %s, %s, %s)
            """,
            (cliente_dni, producto_ref, cantidad, monto),
        )

        mysql.connection.commit()
        flash(f'Venta registrada con éxito para "{producto_ref}".', "success")
        return redirect(url_for("index"))

    except ValueError:
        flash("Error: La cantidad y el monto deben ser números válidos.", "error")
        return redirect(url_for("index"))
    except Exception as e:
        mysql.connection.rollback()
        print(f"Error al registrar la venta: {e}", file=sys.stderr)
        flash(f"Error al registrar la venta: {e}", "error")
        return redirect(url_for("index"))
    finally:
        if cursor:
            cursor.close()


with app.app_context():
    verify_and_update_db_schema()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)