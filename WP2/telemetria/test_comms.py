import rclpy
from rclpy.node import Node
import time

def main():
    rclpy.init()
    node = Node('nodo_de_prueba')
    
    node.get_logger().info('¡Nodo vivo! Ahora búscame en rqt_graph...')
    
    # En lugar de cerrarse, se queda "girando" (spin)
    # Esto mantiene el nodo activo hasta que pulses CTRL+C
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('Cerrando el nodo...')
    
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()