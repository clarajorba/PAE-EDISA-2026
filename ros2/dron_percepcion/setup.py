from setuptools import find_packages, setup

package_name = 'dron_percepcion'

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
    description='Cámara de la Raspberry, detector de códigos de barras y envío imagen+pose',
    license='TODO: License declaration',
    entry_points={
        'console_scripts': [
            'camera_publisher = dron_percepcion.camera_publisher:main',
            'barcode_detector = dron_percepcion.barcode_detector:main',
            'telemetry_publisher = dron_percepcion.telemetry_publisher:main',
        ],
    },
)
