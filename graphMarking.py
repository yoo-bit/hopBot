import pybullet as p
import pybullet_data
import console
import time
import math
import pyqtgraph as pg
import numpy as np
import PyQt5
from pyqtgraph.Qt import QtGui, QtCore
from statistics import mean
from time import sleep
from collections import deque
import matplotlib.pyplot as plt

physicsClient = p.connect(p.GUI)
# Config DebugVisualizer
# Speed up by disable shadows
p.configureDebugVisualizer(p.COV_ENABLE_SHADOWS, 0)
# Disable GUI side windows
p.configureDebugVisualizer(p.COV_ENABLE_GUI, 0)
p.setAdditionalSearchPath(pybullet_data.getDataPath())  # optionally
p.setGravity(0, 0, -10)
planeId = p.loadURDF("plane.urdf")
robotStartPos = [0, 0, 1.2]
robotStartOrientation = p.getQuaternionFromEuler([0, 0, 0])
robotId = p.loadURDF("3dHopper.urdf", robotStartPos, robotStartOrientation)
robotPos, robotOrn = p.getBasePositionAndOrientation(robotId)
useRealTimeSimulation = True
touchDownTime = time.time()
liftOffTime = time.time()
leapEnabled = False
recordDataEnabled = True
# Current state
state = 'NULL'
# Record stance time Ts
Ts = []
# Set desired position
xd = p.addUserDebugParameter('xd', 0, 15, 5)
yd = p.addUserDebugParameter('yd', 0, 15, 0)
# Set position and velocity control feedback kp and kv
kPosition = 0.1
kVelocity = -1
# Set speed limit
maxSpeed = 2.4
# Set control mode to torque control
# Cancel POSITION_CONTROL effect by setting force to 0
# Add target text
# p.addUserDebugText('Target', [p.readUserDebugParameter(xd), p.readUserDebugParameter(yd), 0])
p.setJointMotorControlArray(
    robotId,
    [0, 1, 2],
    p.POSITION_CONTROL,
    targetPositions=[0.0, 0, 0],
    forces=[0, 0, 0]
    )
# Add debug parameters
# Gains for balancing(maintain body attitude)
balanceKp = p.addUserDebugParameter('balanceKp', 0, 500, 200)
balanceKv = p.addUserDebugParameter('balanceKv', 0, 50, 12)
# Gain for foor placement
footFeedbackGain = p.addUserDebugParameter('footFeedbackGain', 0, 0.1, 0.035)
# Record footPlacement position
pitchList = []
bodyAngleList = []
xList = []  # x position
zList = []  # jump height
xdList = []  # desired x position
xfList = []
xfdList = []
xVelocityList = []
xVdList = []
yVelocityList = []
yVdList = []
xVdListUnFiltered = []
springLengthList = []
springTorqueList = []
bodyTorqueList = []
heightList = []
# Real time plot switch
realTimePlot = [False, False]
# Set thrust force
thrustForce = 250
SMALL_SIZE = 13
MEDIUM_SIZE = 16
BIGGER_SIZE = 20

plt.rc('font', size=SMALL_SIZE)          # controls default text sizes
plt.rc('axes', titlesize=SMALL_SIZE)     # fontsize of the axes title
plt.rc('axes', labelsize=MEDIUM_SIZE)    # fontsize of the x and y labels
plt.rc('xtick', labelsize=SMALL_SIZE)    # fontsize of the tick labels
plt.rc('ytick', labelsize=SMALL_SIZE)    # fontsize of the tick labels
plt.rc('legend', fontsize=SMALL_SIZE)    # legend fontsize
plt.rc('figure', titlesize=BIGGER_SIZE)  # fontsize of the figure title
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = 'Source Sans Pro'

def getCurrentState():
    # Get contact info
    contactPoints = p.getContactPoints(
                bodyA=robotId, bodyB=planeId,
                linkIndexA=3, linkIndexB=-1)
    global state
    if contactPoints:
        # Robot entering into loading when first contact with ground from air
        if state == 'FLIGHT':
            state = 'LOADING'
            global touchDownTime
            touchDownTime = time.time()
            # print('LOADING')
        # If leg shortens, enter compression state
        if p.getJointState(robotId, 2)[1] > 0:
            state = 'COMPRESSION'
        # If leg near full length
        elif (abs(p.getJointState(robotId, 2)[0]) < 0.01 and
              p.getJointState(robotId, 2)[1] < 0):
            state = 'UNLOADING'
            global liftOffTime
            liftOffTime = time.time()
            stanceDuration = liftOffTime - touchDownTime
            global Ts
            Ts.append(stanceDuration)
            # print('UNLOADING')
        # If leg lengthens, enter thrust state
        elif p.getJointState(robotId, 2)[1] < 0:
            state = 'THRUST'
    else:
        state = 'FLIGHT'


def sendP(joint, position):
    p.setJointMotorControl2(
        bodyUniqueId=robotId,
        jointIndex=joint,
        controlMode=p.POSITION_CONTROL,
        targetPosition=position,
        maxVelocity=5
        )


def sendTorqueControl(joint, torque):
    p.setJointMotorControl2(
                bodyUniqueId=robotId,
                jointIndex=joint,
                controlMode=p.TORQUE_CONTROL,
                targetPosition=0,
                force=torque)


# Calculate the angle which leg move forward
def calculateDesiredLegAndBodyAngle(
        phi, forwardSpeed, desiredForwardSpeed,
        stancePhaseDuration, r, feedBackGain):
    secondPart = (forwardSpeed * stancePhaseDuration)/(2*r) + \
                 (feedBackGain * (forwardSpeed - desiredForwardSpeed))/r
    desiredAngle = phi - math.asin(secondPart)
    # print('desiredAngle', desiredAngle)
    return desiredAngle


def controlRobot():
    # Foot touch ground, stop exhausting leg and zero hip torque
    if state == 'LOADING':
        pass
    # Upper leg chamber sealed, servo body attitude with hip
    if state == 'COMPRESSION':
        # Seal leg chamber, work like a spring
        legLength = 0.25 + 0.52 - p.getJointState(robotId, 2)[0]
        if abs(p.getJointState(robotId, 2)[1]) < 0.6:
            torque = -thrustForce
        else:
            stiffness = 1 / legLength
            torque = -stiffness * p.getJointState(robotId, 2)[0]
        springTorqueList.append(torque)
        springLengthList.append(legLength)
        # Servo body attitude
        controlBodyAttitude()
    if state == 'THRUST':
        global leapEnabled
        if leapEnabled:
            sendTorqueControl(2, -930)
            sendTorqueControl(0, 222.7)
        else:
        # Pressurize Leg
            sendTorqueControl(2, -thrustForce)
        # Servo body attitude
        controlBodyAttitude()
    if state == 'UNLOADING':
        leapEnabled = False
    if state == 'FLIGHT':
        kp = 47
        kv = 1.26
        # Exhaust leg to low pressure
        sendTorqueControl(2, -10)
        # Position leg for landing
        # X direction
        # Calculate desired foot placment
        forwardSpeedX = p.getBaseVelocity(robotId)[0][0]
        desiredForwardSpeedX = getDesiredSpeed(
                                currentPosition=(
                                 p.getBasePositionAndOrientation(robotId)[0][0]
                                ),
                                currentSpeed=p.getBaseVelocity(robotId)[0][0],
                                targetPosition=p.readUserDebugParameter(xd),
                                kp=kPosition,
                                kv=kVelocity,
                                maxForwardSpeed=maxSpeed)
        if Ts:
            t = Ts[-1]
            desiredHipAngleX = calculateDesiredLegAndBodyAngle(
                phi=p.getBasePositionAndOrientation(robotId)[1][1],
                forwardSpeed=forwardSpeedX,
                desiredForwardSpeed=desiredForwardSpeedX,
                stancePhaseDuration=0.39,
                r=0.75,
                feedBackGain=p.readUserDebugParameter(footFeedbackGain)
                )
            torque = (-kp*(p.getJointState(robotId, 0)[0] - desiredHipAngleX) -
                      kv*p.getJointState(robotId, 0)[1])
            # Control X foot placement
            sendTorqueControl(0, torque)
            # Control Y foot placement
            forwardSpeedY = p.getBaseVelocity(robotId)[0][1]
            desiredForwardSpeedY = getDesiredSpeed(
                                currentPosition=(
                                 p.getBasePositionAndOrientation(robotId)[0][1]
                                ),
                                currentSpeed=p.getBaseVelocity(robotId)[0][1],
                                targetPosition=p.readUserDebugParameter(yd),
                                kp=kPosition,
                                kv=kVelocity,
                                maxForwardSpeed=maxSpeed)
            desiredHipAngleY = -calculateDesiredLegAndBodyAngle(
                phi=p.getBasePositionAndOrientation(robotId)[1][0],
                forwardSpeed=forwardSpeedY,
                desiredForwardSpeed=desiredForwardSpeedY,
                stancePhaseDuration=0.39,
                r=0.75,
                feedBackGain=p.readUserDebugParameter(footFeedbackGain)
                )
            torque2 = (-kp*(p.getJointState(robotId, 1)[0] - desiredHipAngleY)
                       - kv*p.getJointState(robotId, 1)[1])
            sendTorqueControl(1, torque2)
            if leapEnabled:
                sendTorqueControl(0, -45)
            if p.getBasePositionAndOrientation(robotId)[0][2] > 1.5:
                leapEnabled = False


def controlBodyAttitude():
    kp = p.readUserDebugParameter(balanceKp)
    kv = p.readUserDebugParameter(balanceKv)
    # Balance along X axis
    pitchAngle = p.getBasePositionAndOrientation(robotId)[1][1]
    pitchAngleDerivative = p.getBaseVelocity(robotId)[1][1]
    torque = -kp * (pitchAngle - 0) - kv * pitchAngleDerivative
    sendTorqueControl(0, -torque)
    bodyTorqueList.append(-torque)
    # Balance along Y axis
    rollAngle = p.getBasePositionAndOrientation(robotId)[1][0]
    rollAngleDerivative = p.getBaseVelocity(robotId)[1][0]
    torque2 = -kp * (rollAngle - 0) - kv * rollAngleDerivative
    sendTorqueControl(1, -torque2)


# Contain update GUI, robot control and step simulation
# Auto camera tracking
def stepRobotSimulation():
    cameraPos = p.getLinkState(robotId, 0)[0]
    getCurrentState()
    controlRobot()
    p.setGravity(0, 0, -10)
    p.resetDebugVisualizerCamera(1.5, 0, 0, cameraPos)
    p.stepSimulation()


def debug():
    while 1:
        global useRealTimeSimulation
        global state
        global xfList
        global xfdList
        global xVdList
        global xVelocityList
        global Ts
        global plt
        # Single step simulation when pressing down arrow keyboard
        if p.getKeyboardEvents() == {65298: 1}:
            stepRobotSimulation()
            recordData()
            sleep(0.01)
        # Enter console mode when press 'c'
        elif p.getKeyboardEvents() == {99: 1}:
            console.copen(globals(), locals())
        elif p.getKeyboardEvents() == {114: 1}:
            # Enter r to trigger realtime simulation
            useRealTimeSimulation = True
        elif p.getKeyboardEvents() == {116: 1}:
            useRealTimeSimulation = False
        elif p.getKeyboardEvents() == {106: 1}:
            global leapEnabled
            leapEnabled = True
            print('leapEnabled', leapEnabled)
            # Press j to jump(back flip)
        # Press 'p' to reset robot position and orientation
        elif p.getKeyboardEvents() == {112: 1}:
            p.resetBasePositionAndOrientation(robotId, robotStartPos, robotOrn)
            p.resetJointState(robotId, 0, 0, 0)
            p.resetJointState(robotId, 1, 0, 0)
            p.resetJointState(robotId, 2, 0, 0)
            xfList = []
            xfdList = []
            xVdList = []
            xVelocityList = []
            Ts = []
            state = 'NULL'
            p.setJointMotorControlArray(
                robotId,
                [0, 1, 2],
                p.POSITION_CONTROL,
                targetPositions=[0.0, 0, 0],
                forces=[0, 0, 0]
                )
        elif p.getKeyboardEvents() == {51: 1}:
            global recordDataEnabled
            recordDataEnabled = True
        elif p.getKeyboardEvents() == {49: 1}:
            plt = pw.plot(springLengthList, springTorqueList, pen='k', name='Torque')
        elif p.getKeyboardEvents() == {50: 1}:
            plt.figure(figsize=(9, 10))
            ax1 = plt.subplot(511)
            ax1.set_xticklabels([])
            plt.ylabel('Thrust Torque \n (Newton)')
            ax1.get_yaxis().set_label_coords(-0.08,0.5)
            plt.plot(springTorqueList, linewidth=2)
            ax2 = plt.subplot(512)
            ax2.set_xticklabels([])
            plt.ylabel('Body Torque \n (Newton)')
            plt.plot(bodyTorqueList, linewidth=2)
            ax2.get_yaxis().set_label_coords(-0.08,0.5)
            ax3 = plt.subplot(513)
            ax3.set_xticklabels([])
            plt.ylabel('Body Angle \n (Rad)')
            ax3.get_yaxis().set_label_coords(-0.08,0.5)
            plt.plot(bodyAngleList, linewidth=2)
            ax4 = plt.subplot(514)
            ax4.set_xticklabels([])
            ax4.get_yaxis().set_label_coords(-0.08,0.5)
            plt.plot(heightList, linewidth=2)
            plt.ylabel('Body Height \n (Meter)')
            ax5 = plt.subplot(515)
            ax5.get_yaxis().set_label_coords(-0.08,0.5)
            plt.plot(xList, linewidth=2)
            plt.ylabel('Travel Distance \n (Meter)')
            plt.xlabel('Time Step (N)')
            # plt.ylabel('Body Angle(Deg)')
            plt.savefig('raibert.png', dpi=400)
            plt.show()
            return

        if recordDataEnabled:
            recordData()
        if useRealTimeSimulation:
            stepRobotSimulation()
            sleep(0.003)


def recordData():
    xList.append(p.getBasePositionAndOrientation(robotId)[0][0])
    zList.append(p.getBasePositionAndOrientation(robotId)[0][2])
    pitchList.append(p.getBasePositionAndOrientation(robotId)[1][1])
    bodyAngleList.append(p.getJointState(robotId, 0)[0])
    heightList.append(p.getBasePositionAndOrientation(robotId)[0][2])
    xf = (p.getLinkState(robotId, 3)[0][0] -
          p.getLinkState(robotId, 0)[0][0])
    xdList.append(p.readUserDebugParameter(xd))
    xfList.append(xf)
    xfd = (p.getBaseVelocity(robotId)[0][0] * 0.39 / 2 +
           p.readUserDebugParameter(footFeedbackGain) *
           (p.getBaseVelocity(robotId)[0][0]))
    desiredForwardSpeedX = getDesiredSpeed(
                                currentPosition=(
                                 p.getBasePositionAndOrientation(robotId)[0][0]
                                ),
                                currentSpeed=p.getBaseVelocity(robotId)[0][0],
                                targetPosition=xd,
                                kp=kPosition,
                                kv=kVelocity,
                                maxForwardSpeed=maxSpeed)
    xVdList.append(desiredForwardSpeedX)
    xVelocityList.append(p.getBaseVelocity(robotId)[0][0])
    yVelocityList.append(p.getBaseVelocity(robotId)[0][1])


def getDesiredSpeed(currentPosition, currentSpeed, targetPosition,
                    kp, kv, maxForwardSpeed):
        d = min(-kp * (currentPosition - targetPosition) - kv * (currentSpeed),
                maxForwardSpeed)
        xVdListUnFiltered.append(-kp * (currentPosition - targetPosition) -
                                 kv * (currentSpeed))
        return d


# Debug priting function

def pt(name):
    if name == 'xf':
        pg.plot(xfList)
    if name == 'xfd':
        pg.plot(xfdList)
    if name == 'xVelocity':
        print(p.getBaseVelocity(robotId)[0][0])
    if name == 'footPlacementCompare':
        win = pg.GraphicsWindow()
        win.addPlot(xfList, row=0, col=0)


if __name__ == '__main__':
    pg.setConfigOption('background', 'w')
    pg.setConfigOption('foreground', 'k')
    pg.setConfigOptions(antialias=True)
    debug()


# Debug command lines
# p.createConstraint(robotId, -1, -1, -1, p.JOINT_POINT2POINT, [0, 0, 0], [0, 0, 0], [0, 0, 2])
# p.getJointState(robotId,0)
# legLength = p.getLinkState(robotId, 0)[0][2] - p.getLinkState(robotId, 3)[0][2]
# p.getBasePositionAndOrientation(robotId)
# p.getEulerFromQuaternion([0,0,0,1])
# p.getBaseVelocity(robotId)
# p.getLinkState(robotId,3)
