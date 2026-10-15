from setuptools import find_packages, setup

package_name = 'dron_gcs_bridge'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Equipo PAE-EDISA',
    maintainer_email='todo@todo.todo',
    description='Nodos de la Raspberry que dan servicio a la app GCS: gestor de servicios, puente MAVLink y planificador de misión',
    license='TODO: License declaration',
    entry_points={
        'console_scripts': [
            'gcs_control = dron_gcs_bridge.gcs_control:main',
            'mavlink_bridge = dron_gcs_bridge.mavlink_bridge:main',
            'brain_node = dron_gcs_bridge.brain_node:main',
        ],
    },
)
